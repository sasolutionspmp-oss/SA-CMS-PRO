from pathlib import Path
r=Path('/dev/shm/cipher-documents-doc03-successor/workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec')
p=r/'documents/repository.py';s=p.read_text();needle='    def revision_scope(self, name):';s=s.replace(needle,'''    def document_scope(self, name):
        """Internal metadata discovery only; never grants content authority."""
        import frappe
        from cipher_aec.api.errors import DomainError
        row = frappe.db.get_value("Cipher Document", name, ["name", "company", "project", "scope_type"], as_dict=True)
        if not row:
            raise DomainError("not_found", "Document was not found.", 404)
        return row

'''+needle);p.write_text(s)
(r/'document_control/scopes.py').write_text('''"""Explicit document-control source scope; null Project grants no Company authority."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.governance.context import require_company,require_project

def require(company,scope_type,project,actor,ability,*,lock=False):
    if scope_type=='Project' and type(project) is str and project:return require_project(company,project,ability=ability,actor=actor,lock=lock)
    if scope_type=='Company' and project is None:return require_company(company,ability=ability,actor=actor,lock=lock)
    raise DomainError('invalid_document_scope','Declare an explicit Company or Project source scope.',422)

def document(name,company,scope_type,project,actor,*,lock=False):
    require(company,scope_type,project,actor,'document.read',lock=lock)
    row=frappe.get_doc('Cipher Document',name,for_update=lock)
    if row.company!=company or (row.scope_type or 'Project')!=scope_type or (row.project or None)!=(project or None):raise DomainError('not_found','This original source is unavailable.',404)
    return row
''')
p=r/'document_control/service.py';s=p.read_text();old="try:return run_command(company=company,project=project,operation_id=operation_id,command='document.control.'+name+'.v1',payload=payload,ability=ability,guard=guard,effect=effect,participant_people=tuple(sorted(set(plan.values()))))";new="""try:
        from .locking import for_payload
        context=for_payload(company,project,name,payload)
        options={'document_context':context} if context is not None else {}
        return run_command(company=company,project=project,operation_id=operation_id,command='document.control.'+name+'.v1',payload=payload,ability=ability,guard=guard,effect=effect,participant_people=tuple(sorted(set(plan.values()))),**options)""";assert old in s;s=s.replace(old,new);p.write_text(s)
p=r/'governance/commands.py';s=p.read_text();s=s.replace('def run_command(*, company, project, operation_id, command, payload, ability, effect, guard=None, participant_people=()):','def run_command(*, company, project, operation_id, command, payload, ability, effect, guard=None, participant_people=(), document_context=None):',1).replace('command=command, payload=payload, ability=ability, effect=effect, guard=guard, participant_people=participant_people)','command=command, payload=payload, ability=ability, effect=effect, guard=guard, participant_people=participant_people, document_context=document_context)',1).replace('participant_people, draft_save=None):','participant_people, draft_save=None, document_context=None):',1)
s=s.replace('    assert_synthetic_site()','''    if document_context is not None:
        from cipher_aec.document_control.locking import DocumentContext
        if type(document_context) is not DocumentContext or document_context.company!=company or document_context.project!=project:
            raise DomainError('invalid_document_context','Only a concrete server-owned documentary source context is supported.',422)
    assert_synthetic_site()''',1)
s=s.replace('    locked_project = authorize(actor, lock=True)','    if document_context is not None:\n        document_context.prelock(actor)\n    locked_project = authorize(actor, lock=True)',1)
s=s.replace('        with logical_operation(company, command, operation_id) if scope_type == "Company" else nullcontext():','        with (logical_operation(company, command, operation_id) if scope_type == "Company" else nullcontext()), (document_context.hold(actor) if document_context is not None else nullcontext()):',1)
s=s.replace('                with draft_save_boundary:','                with draft_save_boundary, (document_context.hold(actor) if document_context is not None else nullcontext()):',1)
s=s.replace('def authorize_receipt(actor, command, company, project, result, scope_type="Project"):', '''def authorize_receipt(actor, command, company, project, result, scope_type="Project"):
    if scope_type=='Project':
        from cipher_aec.document_control.locking import for_result
        context=for_result(company,project,result)
        if context is not None:
            with context.hold(actor):return _authorize_receipt(actor,command,company,project,result,scope_type)
    return _authorize_receipt(actor,command,company,project,result,scope_type)


def _authorize_receipt(actor, command, company, project, result, scope_type="Project"):''',1)
p.write_text(s)
p=r/'governance/approvals.py';s=p.read_text();s=s.replace('    if scope_type == "Project":\n        return run_command(company=company, project=project, **kwargs)','''    if scope_type == "Project":
        from cipher_aec.document_control.locking import for_approval
        context=for_approval(company,project,kwargs.get('payload',{}))
        if context is not None:kwargs['document_context']=context
        return run_command(company=company, project=project, **kwargs)''',1);p.write_text(s)
# Canonical exact contract authorization without pulling later header units into a historical receipt.
p=r/'document_control/clauses.py';s=p.read_text().replace("value=scoped('revision',name,company,project,actor,lock=lock)","""value=scoped('revision',name,company,project,actor,lock=False)
        if lock:
            from cipher_aec.estimating.units import qualified
            from cipher_aec.engineering.sources import verify
            from cipher_aec.construction_finance import repository as contracts,sources as contract_sources
            from cipher_aec.commercial.native import require_native
            header=contracts.read('contract',value['contract'],lock=True)
            original=contracts.read('revision',name,lock=True)
            if original!=value:raise DomainError('clause_integrity','The immutable contract target changed.',409)
            for unit in value['units']:
                if qualified(unit['id'],actor=actor,lock=True,allow_disabled=True)!=unit:raise DomainError('stale_unit','The exact original contract unit differs.',412)
            require_native('Currency',value['currency'],actor,lock=True)
            contract_sources.party_snapshot(company,project,header['definition'],actor,lock=True,allow_disabled=True)
            verify(company,project,value,actor,lock=True)""")
p.write_text(s)
p=r/'document_control/governance.py';s=p.read_text().replace("operation='ingest' if kind=='adoption_request' else 'distribute'", "operation='ingest' if kind in ('adoption_request','redline') else 'distribute'");p.write_text(s)
