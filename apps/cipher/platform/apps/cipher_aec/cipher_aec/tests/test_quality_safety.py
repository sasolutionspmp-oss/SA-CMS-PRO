"""Substantive host service/controller tests; no native session acceptance claim."""
from copy import deepcopy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from .quality_safety_fixtures import fixtures,uid,add_person,add_source,ROOT

def definition(family='record',category='deficiency'):
    value={'title':'Documented field finding','local_date':'2026-10-17','location':'Grid A',
        'description':'Authored documentary observation only.',
        'required_closure_items':[{'item_id':uid(),'description':'Retain the specified correction and verification evidence.'}]}
    if family=='incident':value.update(involved_people=['Synthetic person'],restricted_account='Restricted witness account.',immediate_response='Recorded response; no medical advice.',shared_evidence_revisions=[],shared_evidence_statement='')
    if category=='permit_record':value.update(issuer_as_recorded='Named issuer as recorded',permit_identifier='DOCUMENT-123',valid_from='2026-10-17T09:00:00-04:00',valid_until='2026-10-17T17:00:00-04:00',conditions_as_recorded='Authored conditions from the retained source.')
    return value

def create(state,service,family='record',category='deficiency',operation=None):
    category='incident' if family=='incident' else category
    evidence=[add_source(state)];authored=definition(family,category)
    if family=='incident':authored.update(shared_evidence_revisions=[evidence[0]['revision_id']],shared_evidence_statement='This exact ordinary source contains no sensitive incident information.')
    return service.create_record('C','P',operation or uid(),family,category,authored,evidence)

def transition(state,service,result,action,*,closure=None,evidence=None,operation=None,version=None):
    if evidence is None:evidence=[add_source(state)] if action=='check' else []
    if closure is None:
        closure=[{'item_id':r['item_id'],'evidence':[add_source(state)]} for r in result['revision']['definition']['required_closure_items']] if action=='close' else []
    return service.transition('C','P',operation or uid(),result['family'],result['header']['id'],version or digest(result['header']),action,'Documentary '+action,evidence,closure)

def checked(state,service,result):
    result=transition(state,service,result,'submit');state.actor=add_person(state,'checker');return transition(state,service,result,'check')

class QualitySafetyTests(unittest.TestCase):
    def test_each_documentary_category_closes_on_current_exact_item_evidence(self):
        for category in ('inspection','deficiency','safety_observation','permit_record'):
            with self.subTest(category=category),fixtures() as (state,rules,repo,sources,service,records):
                first=create(state,service,category=category);result=checked(state,service,first);state.actor=add_person(state,'closer')
                closed=transition(state,service,result,'close')
                self.assertEqual(closed['header']['status'],'closed');self.assertEqual(closed['header']['closed_revision'],first['revision']['id'])
                self.assertEqual(closed['decision']['checked_by_person'],result['decision']['author_person'])
                self.assertEqual(closed['decision']['closure'][0]['evidence'][0]['source_sha256'],state.documents[closed['decision']['closure'][0]['evidence'][0]['revision_id']]['source_sha256'])
                self.assertTrue(all(value is False for value in closed['decision']['no_effects'].values()))

    def test_replay_uses_canonical_person_namespace_and_preserves_original_result(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            operation=uid();authored=definition();evidence=[add_source(state)]
            first=service.create_record('C','P',operation,'record','inspection',authored,evidence)
            alias=SimpleNamespace(user='author-alias@example.invalid',person_id=state.actor.person_id);state.users[alias.user]=alias;state.actor=alias
            replay=service.create_record('C','P',operation,'record','inspection',authored,evidence)
            self.assertEqual(first['revision'],replay['revision']);self.assertTrue(replay['operation']['replayed']);self.assertEqual(len(state.native),2)
            changed={**authored,'description':'Changed payload'}
            with self.assertRaises(DomainError) as caught:service.create_record('C','P',operation,'record','inspection',changed,evidence)
            self.assertEqual(caught.exception.code,'operation_conflict')

    def test_alias_author_cannot_check_and_checker_alias_cannot_close(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            first=create(state,service);submitted=transition(state,service,first,'submit')
            alias=SimpleNamespace(user='author-alias@example.invalid',person_id=state.actor.person_id);state.users[alias.user]=alias;state.actor=alias
            with self.assertRaises(DomainError) as caught:transition(state,service,submitted,'check')
            self.assertEqual(caught.exception.code,'independent_quality_safety_required')
            state.actor=add_person(state,'checker');result=transition(state,service,submitted,'check')
            alias=SimpleNamespace(user='checker-alias@example.invalid',person_id=state.actor.person_id);state.users[alias.user]=alias;state.actor=alias
            with self.assertRaises(DomainError) as caught:transition(state,service,result,'close')
            self.assertEqual(caught.exception.code,'independent_quality_safety_required');self.assertEqual(repo.raw('record',first['header']['id'])['status'],'checked')

    def test_closure_rejects_missing_wrong_duplicate_and_empty_item_evidence(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            result=checked(state,service,create(state,service));state.actor=add_person(state,'closer');item=result['revision']['definition']['required_closure_items'][0]['item_id']
            for closure in ([],[{'item_id':uid(),'evidence':[add_source(state)]}],[{'item_id':item,'evidence':[]}],[{'item_id':item,'evidence':[add_source(state)]}]*2):
                with self.subTest(closure=closure),self.assertRaises(DomainError):transition(state,service,result,'close',closure=closure)
            self.assertEqual(repo.raw('record',result['header']['id'])['status'],'checked')

    def test_new_check_and_close_require_current_revision_and_rights(self):
        for denial in ('is_current','read_denied','ingest_denied','bytes'):
            with self.subTest(denial=denial),fixtures() as (state,rules,repo,sources,service,records):
                result=checked(state,service,create(state,service));state.actor=add_person(state,'closer');source=result['revision']['evidence'][0];row=state.documents[source['revision_id']]
                if denial=='is_current':row['is_current']=False
                elif denial=='bytes':row['content']=b'tampered'
                else:state.rights[row['document_id']]=denial
                before=len(state.native)
                with self.assertRaises(DomainError):transition(state,service,result,'close')
                self.assertEqual(len(state.native),before);self.assertEqual(repo.raw('record',result['header']['id'])['status'],'checked')

    def test_checked_evidence_is_rechecked_before_closure(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            result=checked(state,service,create(state,service));state.actor=add_person(state,'closer')
            state.denied.add(result['decision']['evidence'][0]['revision_id'])
            with self.assertRaises(DomainError):transition(state,service,result,'close')
            self.assertEqual(repo.raw('record',result['header']['id'])['status'],'checked')

    def test_closed_successor_retains_immutable_original_decisions_and_lineage(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            first=create(state,service);original=deepcopy(first['revision']);result=checked(state,service,first);state.actor=add_person(state,'closer');closed=transition(state,service,result,'close');decision=deepcopy(closed['decision'])
            state.actor=state.users[first['revision']['author_user']]
            with self.assertRaises(DomainError):service.revise_record('C','P',uid(),'record',first['header']['id'],digest(closed['header']),definition(),[add_source(state)])
            successor=service.revise_record('C','P',uid(),'record',first['header']['id'],digest(closed['header']),definition(),[add_source(state)],'Corrected the documentary finding.')
            self.assertEqual(successor['header']['status'],'draft');self.assertEqual(successor['header']['closed_revision'],original['id'])
            self.assertEqual(successor['revision']['predecessor'],original['id']);self.assertEqual(successor['revision']['amendment_of'],original['id']);self.assertEqual(successor['revision']['prior_decision'],decision['id'])
            self.assertEqual(repo.raw('revision',original['id']),original);self.assertEqual(repo.raw('decision',decision['id']),decision)

    def test_historical_return_allows_explicit_current_source_correction(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            first=create(state,service);submitted=transition(state,service,first,'submit');state.actor=add_person(state,'checker')
            state.documents[first['revision']['evidence'][0]['revision_id']]['is_current']=False
            with self.assertRaises(DomainError):transition(state,service,submitted,'check')
            returned=transition(state,service,submitted,'return');state.actor=state.users[first['revision']['author_user']]
            revised=service.revise_record('C','P',uid(),'record',first['header']['id'],digest(returned['header']),definition(),[add_source(state)])
            self.assertEqual(revised['revision']['predecessor'],first['revision']['id'])

    def test_stale_version_and_late_receipt_failure_leave_no_partial_facts(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            result=create(state,service);submitted=transition(state,service,result,'submit');state.actor=add_person(state,'checker');before=deepcopy((state.native,state.events,state.receipts))
            with self.assertRaises(DomainError) as caught:transition(state,service,submitted,'check',version=digest(result['header']))
            self.assertEqual(caught.exception.code,'stale_quality_safety');self.assertEqual((state.native,state.events,state.receipts),before)
            state.failed_receipt=True
            with self.assertRaises(RuntimeError):transition(state,service,submitted,'check')
            self.assertEqual((state.native,state.events,state.receipts),before)

    def test_incident_has_no_shared_history_and_ordinary_lists_never_scan_private_storage(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            incident=create(state,service,'incident');state.actor=add_person(state,'ordinary');state.duties[state.actor.person_id]={'project.read','document.read','quality.read'}
            self.assertIsNone(incident['history_id']);self.assertEqual(state.events,[])
            with patch.object(repo,'candidate_rows',return_value=[]) as rows:
                public=service.list_records('C','P','record',count_mode='none')
                self.assertEqual(public['items'],[]);self.assertIsNone(public['total']);self.assertIsNone(public['next_cursor']);self.assertEqual(rows.call_args.args[0],'record')
            with patch.object(repo,'candidate_rows') as rows:
                for kind in ('incident','incident_revision','incident_decision'):
                    with self.assertRaises(DomainError):service.list_records('C','P',kind,count_mode='exact')
                rows.assert_not_called()

    def test_unauthorized_incident_existence_history_and_receipt_reads_fail_before_storage(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            result=create(state,service,'incident');state.actor=add_person(state,'ordinary');state.duties[state.actor.person_id]={'project.read','document.read','quality.read'}
            with patch.object(repo,'raw') as raw:
                for record_id in (result['header']['id'],uid()):
                    with self.assertRaises(DomainError) as caught:service.get_record('C','P','incident',record_id)
                    self.assertEqual(caught.exception.code,'capability_denied')
                with self.assertRaises(DomainError):service.authorize_receipt(state.actor,'C','P',result)
                with self.assertRaises(DomainError):service.authorize_history('incident_revision',result['revision']['id'],'C','P',state.actor,{'record_digest':digest(result['revision'])})
                raw.assert_not_called()
            with self.assertRaises(DomainError):service.get_record('C','P','revision',result['revision']['id'])

    def test_incident_new_and_replay_require_current_restricted_read_and_write(self):
        for duty in ('read','write'):
            with self.subTest(duty=duty),fixtures() as (state,rules,repo,sources,service,records):
                operation=uid();authored=definition('incident','incident');evidence=[add_source(state)]
                authored.update(shared_evidence_revisions=[evidence[0]['revision_id']],shared_evidence_statement='Explicitly non-sensitive shared evidence.')
                result=service.create_record('C','P',operation,'incident','incident',authored,evidence)
                allowed=set(rules.ABILITIES)|{'document.read','project.read'};state.duties[state.actor.person_id]=allowed-{f'safety.incident.{duty}'}
                with self.assertRaises(DomainError):service.create_record('C','P',operation,'incident','incident',authored,evidence)
                with self.assertRaises(DomainError):service.create_record('C','P',uid(),'incident','incident',authored,evidence)
                self.assertEqual(len(state.native),2);self.assertEqual(len(state.receipts),1)

    def test_replayed_evidence_uses_current_read_rights_and_original_not_head(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            operation=uid();authored=definition();evidence=[add_source(state)]
            first=service.create_record('C','P',operation,'record','inspection',authored,evidence)
            source=state.documents[evidence[0]['revision_id']];source['is_current']=False
            replay=service.create_record('C','P',operation,'record','inspection',authored,evidence);self.assertEqual(replay['revision'],first['revision'])
            state.rights[source['document_id']]='read_denied'
            with self.assertRaises(DomainError):service.create_record('C','P',operation,'record','inspection',authored,evidence)

    def test_project_closed_and_cross_scope_sources_fail_without_effect(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            state.project_status='Completed'
            with self.assertRaises(DomainError):create(state,service)
            self.assertEqual(state.native,{})
            state.project_status='Open';source=add_source(state);state.documents[source['revision_id']]['project']='OTHER'
            with self.assertRaises(DomainError):service.create_record('C','P',uid(),'record','inspection',definition(),[source])
            self.assertEqual(state.native,{})

    def test_closed_definition_rejects_incident_fields_and_authority_claims_on_ordinary_records(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            for extra in ('involved_people','restricted_account','medical_diagnosis','permit_approved','hazardous_work_authority','amount','payroll_release','actor_person'):
                with self.subTest(extra=extra),self.assertRaises(DomainError):service.create_record('C','P',uid(),'record','inspection',{**definition(),extra:'forbidden'},[add_source(state)])
            bad=definition(category='permit_record');bad['valid_until']=bad['valid_from']
            with self.assertRaises(DomainError):service.create_record('C','P',uid(),'record','permit_record',bad,[add_source(state)])
            self.assertEqual(state.native,{})

    def test_native_controller_rejects_generic_writes_original_changes_delete_and_rename(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            first=create(state,service);native=state.get_doc(rules.KINDS['revision'],first['revision']['id']);before=deepcopy(state.native)
            with self.assertRaises(DomainError):native.save(ignore_permissions=True)
            tampered={**first['revision'],'definition':{**first['revision']['definition'],'description':'Rewritten'}}
            with self.assertRaises(DomainError):repo.write('revision',tampered,old=first['revision'])
            for method in ('on_trash','before_rename'):
                with self.assertRaises(DomainError):getattr(records.QualitySafetyRecord,method)(native)
            self.assertEqual(state.native,before)

    def test_incident_cursor_cannot_be_reused_by_another_user_or_after_duty_change(self):
        with fixtures() as (state,rules,repo,sources,service,records):
            results=[create(state,service,'incident') for _ in range(2)]
            rows=[SimpleNamespace(name=r['header']['id'],creation='2026-10-17 12:00:00') for r in results]
            with patch.object(repo,'candidate_rows',return_value=rows):page=service.list_records('C','P','incident',limit=1)
            self.assertIsNotNone(page['next_cursor']);state.actor=add_person(state,'another-authorized')
            with self.assertRaises(DomainError) as caught:service.list_records('C','P','incident',limit=1,cursor=page['next_cursor'])
            self.assertEqual(caught.exception.code,'invalid_cursor')
            state.actor=state.users[results[0]['revision']['author_user']];state.duties[state.actor.person_id]={'safety.incident.read','document.read','project.read'}
            with self.assertRaises(DomainError) as caught:service.list_records('C','P','incident',limit=1,cursor=page['next_cursor'])
            self.assertEqual(caught.exception.code,'invalid_cursor')

if __name__=='__main__':unittest.main()
