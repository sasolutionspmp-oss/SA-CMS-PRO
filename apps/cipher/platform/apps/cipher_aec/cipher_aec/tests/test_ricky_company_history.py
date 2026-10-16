"""Prospective command history source tests; no native/HTTP/model claim."""
import ast
from contextlib import contextmanager, nullcontext, ExitStack
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from cipher_aec.api.contracts import canonical_json, digest, operation_id
from cipher_aec.api.errors import DomainError
from cipher_aec.ricky.company_backend import START_COMMAND, CANCEL_COMMAND
from cipher_aec.ricky.company_contracts import DeterministicReadRequest

ROOT = Path(__file__).parents[1]


def function(relative, name, namespace):
    """Execute the actual boundary function with local storage/transport doubles."""
    selected = next(node for node in ast.parse((ROOT / relative).read_text()).body
        if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[selected], type_ignores=[]), str(ROOT / relative), "exec"), namespace)
    return namespace[name]


class CompanyCommandHistoryTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.db = sqlite3.connect(":memory:", isolation_level=None); self.addCleanup(self.db.close)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            CREATE TABLE runs (name TEXT PRIMARY KEY, body TEXT);
            CREATE TABLE `tabCipher Command Receipt` (name TEXT PRIMARY KEY,person TEXT,operation_id TEXT,company TEXT,
                project TEXT,scope_type TEXT,command TEXT,request_hash TEXT,result_json TEXT,result_hash TEXT,state TEXT);
            CREATE TABLE `tabCipher History Event` (name TEXT PRIMARY KEY,creation TEXT,scope_type TEXT,company TEXT,
                project TEXT,actor_person TEXT,event TEXT,subject_type TEXT,subject_id TEXT,operation_id TEXT,
                details_json TEXT,previous_hash TEXT,event_hash TEXT,event_payload TEXT);
        ''')
        self.actor = SimpleNamespace(user="original@cipher.example", person_id="canonical-person")
        self.original_user = self.actor.user
        self.company = "Exact Company"; self.trusted = False; self.company_locked = False
        self.source_allowed = True; self.fail_insert = None; self.effects_enabled = True
        self.callbacks = []; self.enqueued = []; self.order = []; self.sequence = 0
        self.start_id, self.stop_id = str(uuid4()), str(uuid4())
        self.request = {"schema": "cipher.ricky.company.read-request.v1", "pursuit_id": str(uuid4()),
            "action": "aec.pursuit.lookup", "arguments": {}, "sources": [{"citation_id": "a" * 64,
                "revision_id": str(uuid4()), "page": 1, "excerpt_sha256": "b" * 64, "source_sha256": "c" * 64}],
            "measurement_ids": [str(uuid4())]}
        self.fake = SimpleNamespace(db=SimpleNamespace(sql=self.sql,savepoint=self.savepoint,rollback=self.rollback,
            after_commit=SimpleNamespace(add=self.callbacks.append)),get_doc=self.doc,
            QueryDeadlockError=type("Deadlock", (Exception,), {}), QueryTimeoutError=type("Timeout", (Exception,), {}),
            enqueue=lambda *args, **kwargs:self.enqueued.append((args, kwargs)))
        provenance = ModuleType("cipher_aec.documents.provenance")
        provenance.logical_operation = lambda *args, **kwargs:nullcontext()
        provenance.logical_operation_stats = lambda:None
        backend = ModuleType("cipher_aec.ricky.company_backend")
        backend.start_session_binding = lambda **kwargs:nullcontext()
        runtime = ModuleType("cipher_aec.awards.runtime"); runtime.quiet_award_write = lambda record:None
        context = ModuleType("cipher_aec.governance.context"); context.require_effects_enabled = self.require_effects
        api = ModuleType("cipher_aec.ricky.api")
        api._dispatch = function("ricky/api.py", "_dispatch", {"frappe": self.fake})
        self.stack.enter_context(patch.dict("sys.modules", {"cipher_aec.documents.provenance": provenance,
            "cipher_aec.ricky.company_backend": backend, "cipher_aec.awards.runtime": runtime,
            "cipher_aec.governance.context": context,"cipher_aec.ricky.api": api}))
        self.append = function("governance/history.py", "append_company_event", {"frappe":self.fake,
            "require_trusted_write": self.require_trusted,"canonical_json":canonical_json,"digest":digest})
        command = function("governance/commands.py", "_run_scoped_command", {"__package__":"cipher_aec.governance",
            "frappe":self.fake,"DomainError":DomainError,"json":json,"uuid":__import__("uuid"),"nullcontext":nullcontext,
            "assert_synthetic_site":lambda:None,"parse_operation_id":operation_id,"text":lambda value,label:value,
            "current_actor":lambda **kwargs:self.actor,"require_company":self.require_company,"require_project":lambda *a,**k:None,
            "session_authority_reference":lambda actor:"d" * 64,"require_session_authority":lambda *a,**k:None,
            "COMPANY_RICKY_COMMANDS":{START_COMMAND,CANCEL_COMMAND},"digest":digest,"canonical_json":canonical_json,
            "require_effects_enabled":self.require_effects,"trusted_write":self.trusted_write,"authorize_receipt":self.authorize_receipt})
        def run_company_command(**kwargs):
            if not self.db.in_transaction:self.db.execute("BEGIN")
            return command(project=None,scope_type="Company",guard=None,participant_people=(),**kwargs)
        self.service = SimpleNamespace(start_read=self.start_effect,cancel=self.stop_effect)
        namespace = {"__name__":"cipher_aec.ricky.company_api", "__package__":"cipher_aec.ricky", "endpoint":lambda **kwargs:lambda fn:fn,"domain_errors":lambda fn:fn,
            "DeterministicReadRequest":DeterministicReadRequest,"build_service":lambda:self.service,
            "START_COMMAND":START_COMMAND,"CANCEL_COMMAND":CANCEL_COMMAND,"run_company_command":run_company_command,
            "append_company_event":self.append}
        self.start = function("ricky/company_api.py", "start_read", namespace)
        self.stop = function("ricky/company_api.py", "cancel_run", namespace)

    def require_effects(self):
        if not self.effects_enabled:raise DomainError("execution_quarantined", "Explicit source fixture",503)

    def require_trusted(self):
        self.assertTrue(self.trusted,"History must be inside the canonical trusted effect")
        self.assertTrue(self.company_locked,"History must follow the Company lock")

    @contextmanager
    def trusted_write(self):
        self.trusted = True
        try:yield
        finally:self.trusted = False

    def require_company(self, company, **kwargs):
        self.assertEqual(company,self.company)
        if kwargs.get("lock"):self.company_locked = True
        return SimpleNamespace(name=company,status="Open")

    def sql(self, query, parameters=(), as_dict=False):
        if "tabCipher Person" in query:return []
        rows = self.db.execute(query.replace(" FOR UPDATE", "").replace("%s", "?"),parameters).fetchall()
        return [SimpleNamespace(**dict(row)) for row in rows] if as_dict else [tuple(row) for row in rows]

    def savepoint(self, name):self.db.execute("SAVEPOINT " + name)
    def rollback(self, save_point=None):
        self.order.append("rollback")
        self.db.execute("ROLLBACK TO " + save_point if save_point else "ROLLBACK")

    def doc(self, value):
        owner = self
        class Record(SimpleNamespace):
            def insert(self, **kwargs):
                owner.require_trusted()
                data = dict(value); doctype = data.pop("doctype")
                if doctype == "Cipher History Event":
                    owner.sequence += 1; data["name"] = f"history-{owner.sequence:04d}"
                    data["creation"] = f"2026-10-16 12:00:00.{owner.sequence:06d}"
                columns = list(data)
                owner.db.execute("INSERT INTO `tab" + doctype + "` (" + ",".join(columns) + ") VALUES ("
                    + ",".join("?" for _ in columns) + ")",[data[key] for key in columns])
                self.name = data["name"]; owner.order.append(doctype)
                if owner.fail_insert == doctype:raise RuntimeError("Explicit insertion failure after persisted row")
        return Record(**value)

    def start_effect(self, company, request, operation):
        self.require_trusted()
        if not self.source_allowed:raise DomainError("not_found", "Original source denied",404)
        value = {"id":str(uuid4()),"company":company,"scope_type":"Company","project":None,
            "request_kind":"deterministic-read-v1","status":"queued","cancel_requested":False,
            "created_at":"2026-10-16T00:00:00+00:00","completed_at":None,"action":request["action"],
            "selection":request,"selection_digest":DeterministicReadRequest.from_value(request).selection_digest(),
            "standing":DeterministicReadRequest.model_standing(),"result_basis":"original-tool-observation-v1",
            "result":None,"result_digest":None,"error":None}
        self.db.execute("INSERT INTO runs VALUES (?,?)",(value["id"],canonical_json(value)))
        self.order.append("run"); return value

    def stop_effect(self, company, identifier):
        self.require_trusted()
        if self.actor.user != self.original_user:raise DomainError("not_found", "Original User required",404)
        row = self.db.execute("SELECT body FROM runs WHERE name=?",(identifier,)).fetchone()
        value = json.loads(row[0])
        if value["status"] not in ("failed","succeeded","cancelled"):
            value.update(status="cancelled",cancel_requested=True)
            self.db.execute("UPDATE runs SET body=? WHERE name=?",(canonical_json(value),identifier))
        return {key:value[key] for key in ("id","company","scope_type","project","request_kind","status","cancel_requested")}

    def authorize_receipt(self, actor, command, company, project, result, **kwargs):
        if actor.user != self.original_user:raise DomainError("not_found","Original User required",404)
        if command == START_COMMAND and not self.source_allowed:raise DomainError("not_found","Original source denied",404)

    def call_start(self, operation=None):return self.start(self.company,self.request,operation or self.start_id)
    def call_stop(self, run, operation=None):return self.stop(self.company,run,operation or self.stop_id)
    def commit(self):
        self.db.commit()
        callbacks,self.callbacks[:] = list(self.callbacks),[]
        for callback in callbacks:callback()
    def history(self):return [dict(row) for row in self.db.execute("SELECT * FROM `tabCipher History Event` ORDER BY creation,name")]
    def counts(self):return [self.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] for table in ("runs","`tabCipher History Event`","`tabCipher Command Receipt`")]

    def test_start_has_one_canonical_owned_event_without_changing_queued_receipt_or_dispatch(self):
        result = self.call_start()
        self.assertEqual(self.counts(),[1,1,1])
        self.assertFalse(self.trusted); self.assertEqual(self.enqueued,[])
        self.assertEqual(len(self.callbacks),1)
        event = self.history()[0]
        self.assertEqual((event["scope_type"],event["company"],event["project"],event["actor_person"],event["subject_type"],event["subject_id"],event["operation_id"]),
            ("Company",self.company,None,self.actor.person_id,"Cipher Ricky Run",result["id"],self.start_id))
        self.assertEqual(event["event"],"ricky.company.read.start.accepted")
        self.assertEqual(json.loads(event["details_json"]),{"action":"aec.pursuit.lookup","status":"queued"})
        self.assertEqual(event["event_hash"],digest(json.loads(event["event_payload"])))
        body = {key:value for key,value in result.items() if key != "operation"}
        receipt = self.db.execute("SELECT result_json,result_hash FROM `tabCipher Command Receipt`").fetchone()
        self.assertEqual(tuple(receipt),(canonical_json(body),digest(body)))
        self.assertNotIn("history_id",result)
        self.assertLess(self.order.index("Cipher History Event"),self.order.index("Cipher Command Receipt"))
        for private in (self.request["pursuit_id"],self.request["measurement_ids"][0],"b" * 64,"c" * 64,"d" * 64,self.actor.user):
            self.assertNotIn(private,event["event_payload"])
        self.commit();self.assertEqual(len(self.enqueued),1)

    def test_start_and_stop_replay_append_nothing_and_original_queued_body_stays_queued(self):
        admitted = self.call_start(); self.commit()
        stopped = self.call_stop(admitted["id"]); self.commit()
        before = self.history(); counts = self.counts(); jobs = len(self.enqueued)
        start_replay = self.call_start(); stop_replay = self.call_stop(admitted["id"])
        self.assertEqual(start_replay,{**admitted,"operation":{**admitted["operation"],"replayed":True}})
        self.assertEqual(start_replay["status"],"queued")
        self.assertEqual(stop_replay,{**stopped,"operation":{**stopped["operation"],"replayed":True}})
        self.assertEqual(self.history(),before);self.assertEqual(self.counts(),counts)
        self.commit();self.assertEqual(len(self.enqueued),jobs)

    def test_source_free_stop_is_recorded_but_does_not_restore_start_read_or_replay_rights(self):
        admitted = self.call_start();self.commit();self.source_allowed = False
        stopped = self.call_stop(admitted["id"])
        self.assertEqual(stopped["status"],"cancelled")
        self.assertEqual(self.history()[-1]["event"],"ricky.company.read.stop.accepted")
        self.assertEqual(json.loads(self.history()[-1]["details_json"]),{"status":"cancelled","cancel_requested":True})
        with self.assertRaises(DomainError):self.call_start()
        self.assertEqual(len(self.history()),2)
        self.assertTrue(self.call_stop(admitted["id"])["operation"]["replayed"])

    def test_stop_on_successful_or_failed_run_records_acceptance_without_claiming_cancellation(self):
        admitted = self.call_start();self.commit()
        for status in ("succeeded","failed"):
            body = json.loads(self.db.execute("SELECT body FROM runs").fetchone()[0]);body.update(status=status)
            raw = canonical_json(body);self.db.execute("UPDATE runs SET body=?",(raw,))
            stopped = self.call_stop(admitted["id"],str(uuid4()))
            self.assertEqual(stopped["status"],status);self.assertFalse(stopped["cancel_requested"])
            self.assertEqual(self.db.execute("SELECT body FROM runs").fetchone()[0],raw)
            self.assertEqual(json.loads(self.history()[-1]["details_json"]),{"status":status,"cancel_requested":False})
            self.commit()

    def test_history_and_receipt_failures_rollback_run_event_receipt_and_dispatch(self):
        for failed in ("Cipher History Event","Cipher Command Receipt"):
            self.fail_insert = failed
            with self.subTest(failed=failed),self.assertRaisesRegex(RuntimeError,"persisted row"):
                self.call_start()
            self.assertEqual(self.counts(),[0,0,0]);self.assertEqual(self.callbacks,[])
            self.commit();self.assertEqual(self.enqueued,[])
        self.fail_insert = None;self.call_start()
        self.assertEqual(self.history()[0]["previous_hash"],"")

    def test_stop_history_failure_rolls_back_cancellation_and_leaves_existing_start_untouched(self):
        admitted = self.call_start();self.commit()
        before = self.db.execute("SELECT body FROM runs").fetchone()[0]; old = self.history()
        self.fail_insert = "Cipher History Event"
        with self.assertRaises(RuntimeError):self.call_stop(admitted["id"])
        self.assertEqual(self.db.execute("SELECT body FROM runs").fetchone()[0],before)
        self.assertEqual(self.history(),old);self.assertEqual(self.counts(),[1,1,1])

    def test_company_chain_ignores_project_and_foreign_company_heads_and_hashes_previous_event(self):
        for name,scope,company,project in (("old-project","Project",self.company,"real-project"),("foreign","Company","Other Company",None)):
            self.db.execute("INSERT INTO `tabCipher History Event` (name,creation,scope_type,company,project,event_hash) VALUES (?,?,?,?,?,?)",
                (name,"2026-10-16 13:00:00",scope,company,project,"foreign-head"))
        admitted = self.call_start();self.commit();self.call_stop(admitted["id"])
        events = [row for row in self.history() if row["event"]]
        self.assertEqual(events[0]["previous_hash"],"")
        self.assertEqual(events[1]["previous_hash"],events[0]["event_hash"])
        for event in events:self.assertEqual(event["event_hash"],digest(json.loads(event["event_payload"])))

    def test_alias_replay_changed_payload_and_quarantine_cannot_append_events(self):
        admitted = self.call_start();self.commit();before = self.history()
        self.actor = SimpleNamespace(user="alias@cipher.example",person_id=self.actor.person_id)
        with self.assertRaises(DomainError):self.call_start()
        with self.assertRaises(DomainError):self.call_stop(admitted["id"])
        self.actor = SimpleNamespace(user=self.original_user,person_id=self.actor.person_id)
        self.request = {**self.request,"measurement_ids":[]}
        with self.assertRaises(DomainError) as conflict:self.call_start()
        self.assertEqual(conflict.exception.code,"operation_conflict")
        self.effects_enabled = False
        with self.assertRaises(DomainError):self.call_start(str(uuid4()))
        self.assertEqual(self.history(),before)


class CompanyCommandHistoryPrivacyTests(unittest.TestCase):
    """Actual Company authority reader + actual paging with explicit host stores."""
    def setUp(self):
        from .test_ricky_company_service import CompanyStrategyTests
        from cipher_aec.ricky.aec_contracts import SourceReference
        from cipher_aec.ricky import company_service
        from cipher_aec.api import paging
        self.fixture = CompanyStrategyTests(); self.fixture.setUp();self.addCleanup(self.fixture.doCleanups)
        f = self.fixture
        self.owner = f.boundary.actor
        citation = f.boundary.fixture.citation_value
        reference = SourceReference(citation["id"],citation["revision_id"],citation["page"],citation["excerpt_sha256"],citation["source_sha256"])
        request = f.request(sources=(reference,))
        owner_run = f.start(request);f.service.process(owner_run["id"])
        self.owner_run = owner_run["id"]
        self.alias = SimpleNamespace(user="alias@example.test",person_id=self.owner.person_id)
        f.boundary.actor,self.fixture.boundary.user = self.alias,self.alias.user
        alias = f.service.start_read(owner_run["company"],request.binding(),str(uuid4()))
        alias_run = f.store.get("run",alias["id"])
        f.boundary.receipts[alias_run["start_receipt"]] = alias_run["id"]
        f.service.process(alias["id"])
        f.boundary.actor,f.boundary.user = self.owner,self.owner.user
        self.company = owner_run["company"]; self.actor = self.owner
        self.db = sqlite3.connect(":memory:");self.addCleanup(self.db.close);self.db.row_factory = sqlite3.Row
        self.db.execute("CREATE TABLE `tabCipher History Event` (name TEXT,creation TEXT,company TEXT,scope_type TEXT,project TEXT)")
        self.records = {}
        for name,identifier,event in (("b-owner-start",owner_run["id"],"ricky.company.read.start.accepted"),
                ("d-owner-stop",owner_run["id"],"ricky.company.read.stop.accepted"),
                ("c-alias-start",alias["id"],"ricky.company.read.start.accepted"),
                ("e-alias-stop",alias["id"],"ricky.company.read.stop.accepted")):
            self.db.execute("INSERT INTO `tabCipher History Event` VALUES (?,?,?,?,?)",(name,"2026-10-16 12:00:00.000001",self.company,"Company",None))
            self.records[name] = SimpleNamespace(name=name,subject_type="Cipher Ricky Run",subject_id=identifier,event=event)
        fake = SimpleNamespace(DoesNotExistError=type("Missing",(Exception,),{}),
            db=SimpleNamespace(sql=self.sql),get_doc=lambda doctype,name:self.records[name])
        readable = function("governance/history_access.py","readable",{"frappe":fake,"json":json,"DomainError":DomainError,
            "EST_SUBJECTS":{},"TAKEOFF_SUBJECTS":{},"FIN_SUBJECTS":{},"COM_SUBJECTS":{},"require_company":lambda *a,**k:True})
        self.readable = readable
        list_visible = function("governance/history_listing.py","list_visible",{"frappe":fake,"DomainError":DomainError,
            "CHUNK_SIZE":2,"MAX_SCAN":100,"readable":readable,"present_event":lambda event:{"id":event.name,"event":event.event},
            "page_result":paging.page_result})
        listing = ModuleType("cipher_aec.governance.history_listing");listing.list_visible = list_visible
        provenance = ModuleType("cipher_aec.documents.provenance")
        provenance.read_graph_eligible = lambda *args:False;provenance.read_graph = lambda *args:nullcontext()
        self.stack = ExitStack();self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict("sys.modules",{"cipher_aec.governance.history_listing":listing,
            "cipher_aec.documents.provenance":provenance}))
        self.stack.enter_context(patch.object(company_service,"build_service",return_value=f.service))
        self.stack.enter_context(patch.object(paging,"signing_secret",return_value="HOST_ONLY_CURSOR_SECRET"))
        self.history = function("governance/company.py","history",{"__package__":"cipher_aec.governance",
            "current_actor":lambda:self.actor,"require_company":lambda *a,**k:True,"company_authority_fingerprint":lambda *a:"current",
            "page_options":paging.page_options,"decode_cursor":paging.decode_cursor,"signing_secret":paging.signing_secret,"nullcontext":nullcontext})

    def sql(self, query, parameters, as_dict=False):
        rows = self.db.execute(query.replace("%s","?"),parameters).fetchall()
        return [SimpleNamespace(**dict(row)) for row in rows]

    def test_owner_sees_only_exact_original_user_events_and_filtered_total_cursor(self):
        page = self.history(self.company,limit=1,count_mode="exact")
        self.assertEqual(page["total"],2);self.assertEqual([row["id"] for row in page["items"]],["d-owner-stop"])
        self.assertIsNotNone(page["next_cursor"])
        from cipher_aec.api.paging import decode_cursor
        scope = {"scope_type":"Company","company":self.company,"user":self.owner.user,"person":self.owner.person_id,
            "collection":"company_history","authority":"current"}
        last = decode_cursor(page["next_cursor"],secret="HOST_ONLY_CURSOR_SECRET",scope=scope)
        self.assertEqual(last[-1],"d-owner-stop")
        next_page = self.history(self.company,limit=1,count_mode="exact",cursor=page["next_cursor"])
        self.assertEqual(next_page["total"],2);self.assertEqual([row["id"] for row in next_page["items"]],["b-owner-start"])
        self.assertIsNone(next_page["next_cursor"])
        self.assertFalse(self.readable(self.records["d-owner-stop"],self.alias,self.company,None))
        self.assertFalse(self.readable(self.records["d-owner-stop"],SimpleNamespace(user=self.owner.user,person_id="outsider"),self.company,None))
        self.assertFalse(self.readable(self.records["d-owner-stop"],self.owner,self.company,"real-project"))

    def test_revoked_source_native_and_run_rights_hide_events_totals_and_cursors(self):
        f = self.fixture
        for field in ("source_allowed","native_allowed"):
            setattr(f.boundary.fixture,field,False)
            with self.subTest(field=field):
                page = self.history(self.company,limit=1,count_mode="exact")
                self.assertEqual(page["items"],[]);self.assertEqual(page["total"],0);self.assertIsNone(page["next_cursor"])
            setattr(f.boundary.fixture,field,True)
        f.boundary.permission.remove("ricky.run")
        page = self.history(self.company,count_mode="exact")
        self.assertEqual(page["items"],[]);self.assertEqual(page["total"],0);self.assertIsNone(page["next_cursor"])

    def test_source_free_stop_does_not_make_either_history_fact_readable(self):
        f = self.fixture;f.boundary.fixture.source_allowed = False
        stopped = f.service.cancel(self.company,self.owner_run)
        self.assertEqual(stopped["status"],"succeeded")
        self.assertEqual(set(stopped),{"id","company","scope_type","project","request_kind","status","cancel_requested"})
        self.assertFalse(self.readable(self.records["b-owner-start"],self.owner,self.company,None))
        self.assertFalse(self.readable(self.records["d-owner-stop"],self.owner,self.company,None))
        self.assertEqual(self.history(self.company,count_mode="exact")["total"],0)

    def test_alias_cannot_reuse_owner_cursor_even_with_same_person(self):
        page = self.history(self.company,limit=1,count_mode="exact")
        self.actor = self.alias
        with self.assertRaises(DomainError) as error:
            self.history(self.company,limit=1,count_mode="exact",cursor=page["next_cursor"])
        self.assertEqual(error.exception.code,"invalid_cursor")

    def test_source_integrity_error_aborts_exact_scan_instead_of_partial_history(self):
        self.fixture.store.rows["run",self.owner_run]["result_digest"] = "0" * 64
        with self.assertRaises(DomainError) as error:self.history(self.company,limit=1,count_mode="exact")
        self.assertEqual(error.exception.code,"source_integrity")
