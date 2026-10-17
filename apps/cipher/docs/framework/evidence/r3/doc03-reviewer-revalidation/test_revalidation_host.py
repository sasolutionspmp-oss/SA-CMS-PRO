"""Independent source-only DOC03 diagnosis at a3577803.

Real current_actor/require_project/require_company, DocumentContext.discover/
prelock/hold, provenance.prelocked, rights, service._prelock, recipient_read,
domain_approvals.authorize and documentary review callbacks. Native storage,
SQL/session/native-permission and source-byte adapters are explicit doubles.
No nullcontext replacement, runtime, database, approval effect or award call.
"""
import ast,copy,hashlib,importlib,json,os,pathlib,sys,types,unittest
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

ROOT=pathlib.Path(os.environ.get('CIPHER_DOC03_REVIEW_SOURCE',str(pathlib.Path(__file__).parent/'workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec')))
def uid():return str(uuid4())
def module(name,**fields):m=types.ModuleType(name);m.__dict__.update(fields);return m
class Row(dict):
    def __getattr__(self,key):
        try:return self[key]
        except KeyError:raise AttributeError(key)
    def as_dict(self):return dict(self)
    def get(self,key,default=None):return super().get(key,default)

@contextmanager
def fixture(kind):
    for name in list(sys.modules):
        if name in ('cipher_aec.governance.context','cipher_aec.governance.domain_approvals','cipher_aec.documents.provenance','cipher_aec.engineering.sources','cipher_aec.commercial.sources') or name.startswith('cipher_aec.document_control.'):
            sys.modules.pop(name,None);parent,attribute=name.rsplit('.',1)
            if parent in sys.modules and hasattr(sys.modules[parent],attribute):delattr(sys.modules[parent],attribute)
    s=SimpleNamespace(users={'Morgan':'person-morgan','Jordan':'person-jordan'},project_duties={},company_duties={},denied_native=set(),sql=[],native=[],rows={},documents={},revisions={},policies={},source_reads=[])
    duties={'project.read','document.read','document.control.read','document.control.review','approval.decide','approval.execute','document.adopt','document.distribute'}
    s.project_duties={p:set(duties) for p in s.users.values()};s.company_duties={p:{'company.read','document.read','document.control.read'} for p in s.users.values()}
    class DB:
        transaction_writes=0
        before_commit=SimpleNamespace(add=lambda f:None)
        before_rollback=SimpleNamespace(add=lambda f:None)
        def exists(self,*args):return True
        def get_value(self,doctype,name,fields,as_dict=False):
            if doctype=='Cipher Identity Binding':return s.users.get(name['user'])
            values=s.documents if doctype=='Cipher Document' else s.revisions
            value=values.get(name)
            return Row({key:value.get(key) for key in fields}) if value else None
        def sql(self,query,args=(),as_dict=False):
            s.sql.append((query,tuple(args)))
            if query.startswith('SELECT name FROM `tabCipher Person`'):return [(args[0],)]
            if 'WHERE b.user=%s AND b.active=1' in query:
                user=args[-1] if 'AS can_read' in query else args[0]
                person=s.users.get(user)
                if not person:return []
                row=Row(name='binding-'+user,person=person,display_name=user,active=1,binding_modified='1')
                if 'AS can_read' in query:
                    abilities=s.company_duties.get(person,set());row.update(can_read='company.read' in abilities,can_act=args[7] in abilities)
                return [row]
            if 'FROM `tabCipher Project Duty`' in query:
                person=args[0];abilities=(s.company_duties if "scope_type='Company'" in query else s.project_duties).get(person,set())
                return [Row(name=person+'-'+ability,person=person,company='C',project=None if "scope_type='Company'" in query else 'P',ability=ability) for ability in sorted(abilities)]
            if query.startswith('SELECT user FROM `tabCipher Identity Binding`'):
                return [Row(user=user) for user,person in s.users.items() if person==args[0]]
            if query.startswith('SELECT identity_kind'):return [('Human',)]
            raise AssertionError(query)
    db=DB()
    def get_doc(doctype,name,**kwargs):
        if doctype=='Project':return Row(doctype=doctype,name=name,company='C',status='Open')
        if doctype=='Company':return Row(doctype=doctype,name=name)
        if doctype=='Cipher Document':return Row(s.documents[name])
        if doctype=='Cipher Document Revision':return Row(s.revisions[name])
        raise AssertionError((doctype,name))
    def native(doctype,ptype=None,doc=None,user=None,**kw):
        s.native.append((doctype,user));return (doctype,user) not in s.denied_native
    source_service=module('cipher_aec.documents.service')
    source_service.source_reference=lambda *a,**kw:source_impl(*a,**kw)
    source_service.company_source_reference=lambda c,r,p,actor=None,lock=False:source_impl(c,None,r,p,actor=actor,lock=lock,company_scope=True)
    source_service.get_citation=lambda *a,**kw:(_ for _ in ()).throw(AssertionError('No citation needed'))
    mocks={'frappe':module('frappe',db=db,local=SimpleNamespace(db=db),session=SimpleNamespace(user='Morgan'),get_doc=get_doc,has_permission=native,DoesNotExistError=KeyError),
      'frappe.utils':module('frappe.utils',getdate=lambda x:x,nowdate=lambda:'2026-10-17'),
      'cipher_aec.documents.service':source_service,
      'cipher_aec.governance.commands':module('cipher_aec.governance.commands',run_command=lambda **kw:(_ for _ in ()).throw(AssertionError('No command execution'))),
      'cipher_aec.governance.history':module('cipher_aec.governance.history',append_event=lambda **kw:(_ for _ in ()).throw(AssertionError('No event writes'))),
      'cipher_aec.governance.approvals':module('cipher_aec.governance.approvals',require_approval_effect=lambda **kw:(_ for _ in ()).throw(AssertionError('No approval effect'))),
      'cipher_aec.estimating.units':module('cipher_aec.estimating.units',qualified=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unexpected master'))),
      'cipher_aec.commercial.native':module('cipher_aec.commercial.native',require_native=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unexpected master')))}
    with patch.dict(sys.modules,mocks):
        context=importlib.import_module('cipher_aec.governance.context')
        repo=importlib.import_module('cipher_aec.document_control.repository')
        rights=importlib.import_module('cipher_aec.document_control.rights')
        service=importlib.import_module('cipher_aec.document_control.service')
        shared=importlib.import_module('cipher_aec.document_control.shared')
        locking=importlib.import_module('cipher_aec.document_control.locking')
        gov=importlib.import_module('cipher_aec.document_control.governance')
        domain=importlib.import_module('cipher_aec.governance.domain_approvals')
        provenance=importlib.import_module('cipher_aec.documents.provenance')
        lifecycle=importlib.import_module('cipher_aec.document_control.lifecycle')
        def raw(k,name,lock=False):return copy.deepcopy(s.rows[k,name])
        def source_impl(company,project,revision,page,actor=None,lock=False,company_scope=False):
            from cipher_aec.document_control import scopes
            row=s.revisions[revision];scope='Company' if company_scope else 'Project'
            scopes.require(company,scope,project,actor,'document.read',lock=lock)
            rights.authorize({'name':row['document'],'company':company,'project':project,'scope_type':scope},actor,lock=lock)
            s.source_reads.append((actor.user,revision,lock))
            data=row['content']
            return {'document_id':row['document'],'revision_id':revision,'revision_number':1,'source_sha256':hashlib.sha256(data).hexdigest(),'byte_length':len(data),'mime_type':'text/plain','page_count':1,'page':page,'content':data}
        source_service.get_citation=lambda *a,**k:(_ for _ in ()).throw(AssertionError('No citation needed'))
        # engineering.sources captured the adapter before module attributes existed.
        service.sources.source_reference=source_service.source_reference
        origin='Company' if kind=='adoption_request' else 'Project';project=None if origin=='Company' else 'P'
        artifacts=[]
        for index in range(2):
            doc,rev=uid(),uid();data=('exact source '+str(index)).encode()
            s.documents[doc]={'name':doc,'company':'C','scope_type':origin,'project':project,'current_revision':rev,'revision_number':1}
            s.revisions[rev]={'name':rev,'document':doc,'company':'C','scope_type':origin,'project':project,'content':data}
            artifacts.append({'document_id':doc,'revision_id':rev,'revision_number':1,'source_sha256':hashlib.sha256(data).hexdigest(),'byte_length':len(data),'mime_type':'text/plain','page_count':1})
        artifact,evidence=artifacts
        s.policies[artifact['document_id']]={'id':uid(),'parent_id':artifact['document_id'],'company':'C','project':project,'scope_type':origin,'valid_from':None,'valid_until':None,'read_allowed':True,'ingest_allowed':True,'distribute_allowed':True,'evidence_artifact':evidence}
        requester=context.current_actor('Morgan');reviewer=context.current_actor('Jordan')
        base={'company':'C','project':'P','scope_type':'Project','author_person':requester.person_id,'artifacts':[artifact]}
        if kind=='adoption_request':
            header_id,revision_id,subject_id=uid(),uid(),uid()
            header={'id':header_id,'company':'C','scope_type':'Company','project':None,'revision_number':1,'current_revision':revision_id}
            revision={**base,'id':revision_id,'scope_type':'Company','project':None,'parent_id':header_id,'revision_number':1,'predecessor':None}
            subject={**base,'id':subject_id,'parent_id':header_id,'library_revision':revision_id,'library_digest':digest(revision),'library_scope':{'scope_type':'Company','project':None},'definition':{'purpose':'Exact retained reuse','target_locator':'Section 3'}}
            s.rows.update({('library',header_id):header,('library_revision',revision_id):revision,('adoption_request',subject_id):subject})
        else:
            issue_id,subject_id=uid(),uid();issue={**base,'id':issue_id,'package_digest':'a'*64}
            subject={**base,'id':subject_id,'parent_id':issue_id,'issue_id':issue_id,'issue_digest':digest(issue),'package_digest':issue['package_digest'],'recipients':[{'person':reviewer.person_id,'user':reviewer.user}]}
            s.rows['transmittal',subject_id]=subject
        action=gov.rules.ACTIONS[kind]
        manifest={'effect':{'schema':'cipher.document.authorization.v1','action':action,'subject_kind':kind,'subject_id':subject_id,'subject_digest':digest(subject)}}
        packet=SimpleNamespace(name=uid(),company='C',project='P',scope_type='Project',action=action,subject_id=subject_id,manifest_json=json.dumps({'domain':manifest}))
        original_read=service.read
        def read(kind,name,company,project,actor,lock=False):
            if kind=='issue' and origin=='Project':
                context.require_project(company,project,ability='document.control.read',actor=actor,lock=lock)
                service.verify_artifacts(issue['artifacts'],company,project,actor,lock=lock)
                return issue
            return original_read(kind,name,company,project,actor,lock=lock)
        with patch.object(repo,'raw',raw),patch.object(repo,'latest',lambda k,p,lock=False:s.policies.get(p) if k=='rights' else None),patch.object(repo,'official',lambda *a,**kw:None),patch.object(service,'read',read),patch.object(lifecycle,'require_current_issue',lambda value,actor,lock=False:context.require_project('C','P',ability='document.control.read',actor=actor,lock=lock)):
            ctx=locking.DocumentContext('C','P',[(kind,subject_id)],recipients=subject.get('recipients',()))
            yield SimpleNamespace(state=s,context=context,locking=locking,provenance=provenance,service=service,domain=domain,packet=packet,requester=requester,reviewer=reviewer,ctx=ctx,artifact=artifact)

def reviewer_loop(values):
    """Compile the exact current reviewer loop and final generic error from source."""
    text=(ROOT/'governance/approvals.py').read_text()
    if os.environ.get('CIPHER_DOC03_DIAGNOSTIC_PATCH')=='1':
        old='                except DomainError:\n                    reviewer = None'
        new='                except DomainError as error:\n                    if error.code in ("document_prelock_required", "source_prelock_required"):\n                        raise\n                    reviewer = None'
        if text.count(old)!=1:raise AssertionError('Diagnostic patch source no longer matches the pinned reviewer loop')
        text=text.replace(old,new)
    tree=ast.parse(text)
    execute=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='execute_packet')
    effect=next(n for n in execute.body if isinstance(n,ast.FunctionDef) and n.name=='effect')
    scope=next(n for n in effect.body if isinstance(n,ast.With))
    start=next(i for i,n in enumerate(scope.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='reviewer_users' for t in n.targets))
    end=next(i for i,n in enumerate(scope.body[start:],start) if isinstance(n,ast.If) and isinstance(n.test,ast.BoolOp) and any(isinstance(t,ast.Compare) and isinstance(t.left,ast.Name) and t.left.id=='reviewer' for t in n.test.values))
    statements=scope.body[start:end+1]
    env={'packet':values.packet,'decisions':[SimpleNamespace(actor_person=values.reviewer.person_id)],'frappe':sys.modules['frappe'],'current_actor':values.context.current_actor,'company':'C','project':'P','scope_type':'Project','ACTION':'project.status.change.v1','domain_approvals':values.domain,'DomainError':DomainError,'_scope':lambda c,p,s,ability,actor,lock:values.context.require_project(c,p,ability=ability,actor=actor,lock=lock)}
    exec(compile(ast.Module(body=statements,type_ignores=[]),str(ROOT/'governance/approvals.py'),'exec'),env)
    return env['reviewer']

class ReviewSourceTests(unittest.TestCase):
    def test_company_review_hits_real_actor_bound_prelock_and_is_masked(self):
        with fixture('adoption_request') as v, v.ctx.hold(v.requester):
            v.context.require_project('C','P',ability='approval.decide',actor=v.reviewer,lock=True)
            v.context.require_company('C',ability='document.read',actor=v.reviewer,lock=True)
            with self.assertRaises(DomainError) as inner:v.domain.authorize(v.packet,v.reviewer,phase='review',lock=True)
            self.assertEqual((inner.exception.code,inner.exception.status),('document_prelock_required',409))
            with self.assertRaises(DomainError) as outer:reviewer_loop(v)
            self.assertEqual((outer.exception.code,outer.exception.status),('reviewer_authority_revoked',403))
    def test_project_transmittal_review_hits_real_recipient_guard_and_is_masked(self):
        with fixture('transmittal') as v, v.ctx.hold(v.requester):
            with self.assertRaises(DomainError) as inner:v.domain.authorize(v.packet,v.reviewer,phase='review',lock=True)
            self.assertEqual((inner.exception.code,inner.exception.status),('document_prelock_required',409))
            with self.assertRaises(DomainError) as outer:reviewer_loop(v)
            self.assertEqual(outer.exception.code,'reviewer_authority_revoked')
    def test_independent_read_checks_do_not_replace_or_borrow_requester_context(self):
        for kind in ('adoption_request','transmittal'):
            with self.subTest(kind=kind),fixture(kind) as v,v.ctx.hold(v.requester):
                active=v.locking._active.get();token=v.provenance._prelocked.get()
                self.assertEqual(v.domain.authorize(v.packet,v.reviewer,phase='review',lock=False)['id'],v.packet.subject_id)
                self.assertIs(v.locking._active.get(),active);self.assertEqual(v.provenance._prelocked.get(),token)
                self.assertEqual(token[:2],(v.requester.user,v.requester.person_id))
                self.assertTrue(any(user=='Jordan' and not lock for user,rev,lock in v.state.source_reads))
    def test_missing_reviewer_company_duty_and_native_permission_still_deny_fresh_read(self):
        with fixture('adoption_request') as v,v.ctx.hold(v.requester):
            v.state.company_duties[v.reviewer.person_id].remove('document.read')
            with self.assertRaises(DomainError):v.domain.authorize(v.packet,v.reviewer,phase='review',lock=False)
            v.state.company_duties[v.reviewer.person_id].add('document.read');v.state.denied_native.add(('Company','Jordan'))
            with self.assertRaises(DomainError):v.domain.authorize(v.packet,v.reviewer,phase='review',lock=False)
    def test_revoked_current_rights_and_nonindependent_person_remain_denied(self):
        with fixture('transmittal') as v,v.ctx.hold(v.requester):
            v.state.policies[v.artifact['document_id']]['distribute_allowed']=False
            with self.assertRaises(DomainError) as error:v.domain.authorize(v.packet,v.reviewer,phase='review',lock=False)
            self.assertEqual(error.exception.code,'source_rights_denied')
            v.state.policies[v.artifact['document_id']]['distribute_allowed']=True
            with self.assertRaises(DomainError) as error:v.domain.authorize(v.packet,v.requester,phase='review',lock=False)
            self.assertEqual(error.exception.code,'independent_document_review')

    def test_requester_union_does_not_prelock_nonrecipient_reviewer_company_duties(self):
        with fixture('adoption_request') as v,v.ctx.hold(v.requester):
            before=len(v.state.sql)
            v.domain.authorize(v.packet,v.reviewer,phase='review',lock=False)
            queries=v.state.sql
            locked_company=[args[0] for sql,args in queries if "scope_type='Company'" in sql and 'FROM `tabCipher Project Duty`' in sql and 'FOR UPDATE' in sql]
            self.assertIn(v.requester.person_id,locked_company)
            self.assertNotIn(v.reviewer.person_id,locked_company)
            self.assertTrue(any('AS can_read' in sql and args[-1]=='Jordan' for sql,args in queries[before:]))

class IntendedBehaviorRegression(unittest.TestCase):
    """Fail-first acceptance targets for the local fix owner, not a native run.

Current pinned source fails both with reviewer_authority_revoked. Keep the
diagnostic controls separate; a host green result after a composed fix still
does not establish native authority, locking or transactional acceptance.
"""
    def test_authorized_company_source_reviewer_survives_requester_execution(self):
        with fixture('adoption_request') as v,v.ctx.hold(v.requester):
            self.assertEqual(reviewer_loop(v).person_id,v.reviewer.person_id)
    def test_authorized_project_transmittal_reviewer_survives_requester_execution(self):
        with fixture('transmittal') as v,v.ctx.hold(v.requester):
            self.assertEqual(reviewer_loop(v).person_id,v.reviewer.person_id)

class DiagnosticPatchTests(unittest.TestCase):
    def test_diagnostic_only_patch_preserves_inner_denial_and_requester_tokens(self):
        for kind in ('adoption_request','transmittal'):
            with self.subTest(kind=kind),fixture(kind) as v,v.ctx.hold(v.requester),patch.dict(os.environ,{'CIPHER_DOC03_DIAGNOSTIC_PATCH':'1'}):
                active=v.locking._active.get();token=v.provenance._prelocked.get()
                with self.assertRaises(DomainError) as error:reviewer_loop(v)
                self.assertEqual((error.exception.code,error.exception.status),('document_prelock_required',409))
                self.assertIs(v.locking._active.get(),active);self.assertEqual(v.provenance._prelocked.get(),token)

if __name__=='__main__':unittest.main()
