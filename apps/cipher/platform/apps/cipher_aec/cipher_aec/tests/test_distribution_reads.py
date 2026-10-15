"""Bounded instruction inventory SQL, current visibility and canonical choices."""
from contextlib import contextmanager
from types import SimpleNamespace
import sqlite3
import unittest
from unittest.mock import Mock, patch

from cipher_aec.api import paging
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.documents import provenance
from cipher_aec.integrations import distribution as service, distribution_contracts as rules

ISSUE="11111111-1111-4111-8111-111111111111"
OTHER_ISSUE="22222222-2222-4222-8222-222222222222"


class DistributionReadTests(unittest.TestCase):
    def setUp(self):
        self.database=sqlite3.connect(":memory:");self.database.row_factory=sqlite3.Row
        self.addCleanup(self.database.close)
        self.database.execute("CREATE TABLE `tabCipher Distribution Instruction` (name TEXT,creation TEXT,company TEXT,scope_type TEXT,project TEXT,issue_id TEXT)")
        self.actor=SimpleNamespace(user="author@cipher.example",person_id="person-exact")
        self.values={};self.denied={};self.calls=[];self.active=False
        self.issued=[{"name":"First","email":"first@example.invalid","organization":"One"},
            {"name":"Second","email":"second@example.invalid","organization":"Two"}]
        self.issue={"id":ISSUE,"prepared_output":{"binding":{"recipients":self.issued}}}
        self.sql_mock=Mock(side_effect=self.sql)
        self.patches=[patch.object(service,"frappe",SimpleNamespace(db=SimpleNamespace(sql=self.sql_mock))),patch.object(service,"current_actor",return_value=self.actor),
            patch.object(service,"require_company"),patch.object(service,"issue_source",return_value=self.issue),
            patch.object(service,"read",side_effect=self.read),patch.object(paging,"signing_secret",return_value="private-test-key"),
            patch("cipher_aec.governance.context.company_authority_fingerprint",return_value="authority-current"),
            patch.object(provenance,"read_graph_eligible",return_value=True),patch.object(provenance,"read_graph",side_effect=self.graph)]
        self.mocks=[]
        for p in self.patches:
            self.mocks.append(p.start())
            self.addCleanup(p.stop)

    def sql(self,statement,parameters,**kwargs):
        return [SimpleNamespace(**dict(row)) for row in self.database.execute(statement.replace("%s","?"),parameters).fetchall()]

    @contextmanager
    def graph(self,actor,company):
        self.active=True
        try:yield
        finally:self.active=False

    def read(self,kind,name,company,actor):
        self.assertEqual(kind,"instruction");self.assertTrue(self.active)
        self.calls.append(name)
        if name in self.denied:raise self.denied[name]
        return self.values[name]

    def row(self,index,*,issue=ISSUE,company="Company A",scope="Company",project=None,creation="2026-10-15 12:00:00.123456"):
        name=f"00000000-0000-4000-8000-{index:012d}"
        self.database.execute("INSERT INTO `tabCipher Distribution Instruction` VALUES (?,?,?,?,?,?)",(name,creation,company,scope,project,issue))
        self.values[name]={"id":name,"issue_id":issue}
        return name

    def test_choices_are_exact_server_identity_order_and_reusable_subset(self):
        result=service.recipient_choices("Company A",ISSUE)
        self.assertEqual(result,{"issue_id":ISSUE,"issue_digest":digest(self.issue),"recipients":rules.chosen_recipients(self.issued,None)})
        self.assertEqual(rules.chosen_recipients(self.issued,[result['recipients'][1]['id']]),[result['recipients'][1]])
        self.mocks[3].assert_called_once_with("Company A",ISSUE,self.actor)
        self.mocks[-1].assert_not_called()
        changed=[{**self.issued[0],"email":"changed@example.invalid"},self.issued[1]]
        self.assertNotEqual(rules.chosen_recipients(changed,None)[0]["id"],result['recipients'][0]['id'])

    def test_off_page_denied_instructions_cannot_affect_total_or_cursor(self):
        private=self.row(1);visible=self.row(3);missing=self.row(2)
        self.denied={private:DomainError("capability_denied","Private source",403),missing:DomainError("not_found","Unavailable source",404)}
        result=service.list_instructions("Company A",limit=1,count_mode="exact")
        self.assertEqual(result['items'],[{"instruction":self.values[visible],"version":digest(self.values[visible])}])
        self.assertEqual(result['total'],1);self.assertIsNone(result['next_cursor'])
        self.assertEqual(set(self.calls),{private,visible,missing})
        self.assertFalse(self.active)

    def test_native_sql_keyset_ties_and_global_count_preserved(self):
        ids=[self.row(i) for i in range(1,5)]
        first=service.list_instructions("Company A",limit=1,count_mode="exact")
        second=service.list_instructions("Company A",limit=1,cursor=first['next_cursor'],count_mode="exact")
        self.assertEqual(first['items'][0]['instruction']['id'],ids[-1])
        self.assertEqual(second['items'][0]['instruction']['id'],ids[-2])
        self.assertEqual(first['total'],4);self.assertEqual(second['total'],4)
        self.assertEqual(len(self.calls),8)

    def test_cursor_binds_filter_count_mode_company_user_person_and_authority(self):
        self.row(1);self.row(2)
        first=service.list_instructions("Company A",limit=1,count_mode="exact");cursor=first['next_cursor']
        variants=[lambda:service.list_instructions("Company A",cursor=cursor,count_mode="none"),
            lambda:service.list_instructions("Company A",issue_id=ISSUE,cursor=cursor,count_mode="exact"),
            lambda:service.list_instructions("Company B",cursor=cursor,count_mode="exact")]
        for call in variants:
            with self.assertRaises(DomainError) as error:call()
            self.assertEqual(error.exception.code,"invalid_cursor")
        for field,value in (("user","alias@cipher.example"),("person_id","other-person")):
            original=getattr(self.actor,field);setattr(self.actor,field,value)
            try:
                with self.assertRaises(DomainError):service.list_instructions("Company A",cursor=cursor,count_mode="exact")
            finally:setattr(self.actor,field,original)
        self.mocks[6].return_value="changed-authority"
        with self.assertRaises(DomainError):service.list_instructions("Company A",cursor=cursor,count_mode="exact")
        self.assertEqual(len(self.calls),2)

    def test_exact_issue_filter_and_scope_exclude_other_records_before_read(self):
        included=self.row(1);self.row(2,issue=OTHER_ISSUE);self.row(3,company="Company B")
        self.row(4,scope="Project",project="real-project");self.row(5,project="real-project")
        result=service.list_instructions("Company A",issue_id=ISSUE,count_mode="exact")
        self.assertEqual([r['instruction']['id'] for r in result['items']],[included])
        self.assertEqual(result['total'],1);self.assertEqual(self.calls,[included])
        self.mocks[3].assert_called_once_with("Company A",ISSUE,self.actor)

    def test_integrity_and_overflow_propagate_without_partial_inventory(self):
        bad=self.row(1);self.row(2)
        self.denied[bad]=DomainError("distribution_integrity","Corrupt immutable source",409)
        with self.assertRaises(DomainError) as error:service.list_instructions("Company A",limit=1,count_mode="exact")
        self.assertEqual(error.exception.code,"distribution_integrity");self.assertFalse(self.active)
        self.denied.clear();self.calls.clear()
        for i in range(3,502):self.row(i)
        with self.assertRaises(DomainError) as error:service.list_instructions("Company A",limit=1)
        self.assertEqual(error.exception.code,"distribution_limit");self.assertEqual(self.calls,[])

    def test_scope_or_filter_denial_precedes_graph_and_query(self):
        self.mocks[2].side_effect=DomainError("not_found","Unavailable scope",404)
        with self.assertRaises(DomainError):service.list_instructions("Company A")
        self.sql_mock.assert_not_called();self.mocks[-1].assert_not_called()
        self.mocks[2].side_effect=None
        self.mocks[3].side_effect=DomainError("not_found","Unavailable Issue",404)
        with self.assertRaises(DomainError):service.list_instructions("Company A",issue_id=ISSUE)
        self.sql_mock.assert_not_called();self.mocks[-1].assert_not_called()

    def test_current_source_denial_is_rechecked_on_next_inventory(self):
        identifier=self.row(1)
        self.assertEqual(service.list_instructions("Company A",count_mode="exact")['total'],1)
        self.denied[identifier]=DomainError("capability_denied","Source right revoked",403)
        hidden=service.list_instructions("Company A",count_mode="exact")
        self.assertEqual(hidden['items'],[]);self.assertEqual(hidden['total'],0);self.assertIsNone(hidden['next_cursor'])
        self.assertEqual(self.calls,[identifier,identifier])


class DistributionDeliveryIdentityTests(unittest.TestCase):
    def setUp(self):
        from uuid import uuid4
        from cipher_aec.api.contracts import canonical_json
        self.dispatch_id=str(uuid4())
        recipients=rules.chosen_recipients([{"name":"One","email":"one@example.invalid","organization":"Synthetic"},
            {"name":"Two","email":"two@example.invalid","organization":"Synthetic"}],None)
        self.instruction={"id":str(uuid4()),"company":"Company A","issue_id":ISSUE,"recipients":recipients,
            "attachment":{"sha256":"a"*64,"byte_length":100,"revision_id":"REV-original","document_id":"DOC-original","media_type":"application/pdf"},
            "message":{"subject":"Exact original","body":"Same PDF; distinct recipient intents"},"profile":{"id":rules.PROFILE,"version":1,"mode":"fixture"}}
        self.dispatch={"id":self.dispatch_id,"company":"Company A","instruction_id":self.instruction['id'],
            "instruction_digest":digest(self.instruction),"issue_id":ISSUE}
        self.rows=[]
        for number,recipient in enumerate(recipients):
            payload={"schema":"cipher.distribution.payload.v1","company":"Company A","dispatch_id":self.dispatch_id,
                "instruction_id":self.instruction['id'],"instruction_digest":digest(self.instruction),"issue_id":ISSUE,
                "recipient":recipient,"attachment":self.instruction['attachment'],"message":self.instruction['message'],
                "profile":self.instruction['profile'],"mode":"fixture"}
            logical=rules.logical_key(self.dispatch_id,recipient['id']);checksum=digest(payload)
            ack={"mode":"fixture","logical_key":logical,"payload_hash":checksum,"attachment_sha256":"a"*64,
                "byte_length":100,"acknowledgment_id":str(uuid4()),"accepted_at":"2026-10-15T20:00:00+00:00"}
            self.rows.append(SimpleNamespace(name=f"operation-{number}",state="Succeeded",payload_json=canonical_json(payload),
                logical_id=logical,payload_hash=checksum,recipient_id=recipient['id'],result_json=canonical_json({"mode":"fixture","receipt":ack}),last_error_code=None))
        self.patches=[patch.object(service,"read",return_value=self.dispatch),patch.object(service,"raw",return_value=self.instruction),
            patch.object(service,"frappe",SimpleNamespace(db=SimpleNamespace(sql=Mock(side_effect=lambda *args,**kwargs:self.rows)))),patch.object(service,"cancellation",return_value=None)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def get(self):return service.get_dispatch("Company A",self.dispatch_id,actor=SimpleNamespace(user="author@cipher.example",person_id="person"))

    def test_current_read_exposes_expected_keys_and_preserves_original_results(self):
        original=[(r.payload_json,r.result_json) for r in self.rows]
        result=self.get();self.assertEqual(result['state'],"SucceededFixture")
        for delivery,row in zip(result['deliveries'],self.rows):
            self.assertEqual(delivery['logical_key'],row.logical_id)
            self.assertEqual(delivery['payload_hash'],row.payload_hash)
            self.assertEqual(delivery['receipt']['receipt']['logical_key'],delivery['logical_key'])
        self.assertEqual([(r.payload_json,r.result_json) for r in self.rows],original)

    def test_swapped_same_pdf_acknowledgment_never_verifies_other_recipient(self):
        import json
        self.assertEqual(json.loads(self.rows[0].result_json)['receipt']['attachment_sha256'],json.loads(self.rows[1].result_json)['receipt']['attachment_sha256'])
        self.rows[0].result_json=self.rows[1].result_json
        with self.assertRaises(DomainError) as error:self.get()
        self.assertEqual(error.exception.code,"distribution_integrity")

    def test_missing_duplicate_and_unapproved_recipient_rows_fail_integrity(self):
        from copy import copy
        original=list(self.rows)
        for changed in (original[:1],[original[0],copy(original[0])]):
            self.rows=changed
            with self.assertRaises(DomainError):self.get()
        self.rows=original
        self.rows[0].recipient_id="b"*64
        with self.assertRaises(DomainError):self.get()

    def test_payload_index_hash_dispatch_and_attachment_mismatches_fail(self):
        import json
        row=self.rows[0]
        original={k:getattr(row,k) for k in ('logical_id','payload_hash','payload_json','recipient_id')}
        for field,value in (('logical_id','0'*64),('payload_hash','0'*64),('recipient_id',self.rows[1].recipient_id)):
            setattr(row,field,value)
            with self.subTest(field=field),self.assertRaises(DomainError):self.get()
            setattr(row,field,original[field])
        for field,value in (('dispatch_id','wrong-dispatch'),('attachment',{**self.instruction['attachment'],'sha256':'b'*64})):
            payload=json.loads(original['payload_json']);payload[field]=value
            row.payload_json=json.dumps(payload);row.payload_hash=digest(payload)
            with self.subTest(payload_field=field),self.assertRaises(DomainError):self.get()
            row.payload_json=original['payload_json'];row.payload_hash=original['payload_hash']

    def test_success_requires_ack_but_unknown_without_ack_remains_unknown(self):
        self.rows[0].result_json=None
        with self.assertRaises(DomainError):self.get()
        self.rows[0].state="Unknown"
        result=self.get()
        self.assertEqual(result['state'],"Unknown")
        self.assertIsNone(result['deliveries'][0]['receipt'])
        self.assertEqual(result['deliveries'][1]['state'],"Succeeded")

    def test_worker_attempt_metadata_remains_readable_without_becoming_acknowledgment(self):
        import json
        attempt={"attempt_not_after":"2026-10-15T20:00:30Z","mode":"fixture"}
        self.rows[0].result_json=json.dumps(attempt)
        for state in ("Unknown","Claimed","Failed","Cancelled"):
            with self.subTest(state=state):
                self.rows[0].state=state
                delivery=self.get()['deliveries'][0]
                self.assertEqual(delivery['state'],state)
                self.assertEqual(delivery['receipt'],attempt)
                self.assertNotIn('receipt',delivery['receipt'])
        self.rows[0].state="Succeeded"
        with self.assertRaises(DomainError):self.get()

    def test_malformed_attempt_metadata_or_impossible_queued_attempt_fails(self):
        import json
        for state,result in (("Unknown",{"attempt_not_after":"not-a-time","mode":"fixture"}),
                ("Unknown",{"attempt_not_after":"2026-10-15T20:00:30","mode":"fixture"}),
                ("Unknown",{"attempt_not_after":"2026-10-15T20:00:30Z","mode":"fixture","receipt":{}}),
                ("Queued",{"attempt_not_after":"2026-10-15T20:00:30Z","mode":"fixture"})):
            with self.subTest(state=state,result=result):
                self.rows[0].state=state;self.rows[0].result_json=json.dumps(result)
                with self.assertRaises(DomainError):self.get()

    def test_legacy_embedded_delivery_schema_keeps_optional_identity_compatibility(self):
        import json
        from pathlib import Path
        from jsonschema import Draft202012Validator, FormatChecker
        schema=json.loads((Path(__file__).parents[1]/'integrations/schemas/distribution-v1.schema.json').read_text())
        current=self.get()['deliveries'][0]
        legacy={k:v for k,v in current.items() if k not in {'logical_key','payload_hash'}}
        validator=Draft202012Validator({**schema,'$ref':'#/$defs/DistRecipientDelivery'},format_checker=FormatChecker())
        validator.validate(current);validator.validate(legacy)
        self.assertNotIn('logical_key',legacy)
        self.assertEqual(legacy['receipt'],current['receipt'])
