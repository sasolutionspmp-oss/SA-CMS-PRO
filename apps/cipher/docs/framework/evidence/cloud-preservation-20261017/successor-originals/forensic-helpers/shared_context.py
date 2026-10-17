from pathlib import Path
r=Path('/dev/shm/cipher-documents-doc03-successor/workspace/apps/cipher/platform/apps/cipher_aec/cipher_aec')
p=r/'document_control/shared.py';s=p.read_text().replace('from cipher_aec.governance.commands import run_company_command\n','').replace('from cipher_aec.governance.history import append_company_event\n','').replace('    from .locking import DocumentContext\n', '    from .locking import DocumentContext\n    from cipher_aec.governance.commands import run_company_command\n',1).replace("    details={'record_digest':digest(value)","    from cipher_aec.governance.history import append_company_event\n    details={'record_digest':digest(value)",1);p.write_text(s)
p=r/'document_control/locking.py';s=p.read_text().replace('roots=(),targets=(),artifacts=()):','roots=(),targets=(),artifacts=(),documents=(),scope_type=\'Project\'):').replace('self.company,self.project=company,project','self.company,self.project,self.scope_type=company,project,scope_type').replace('self.artifacts=deepcopy(list(artifacts));self.initial=None','self.artifacts=deepcopy(list(artifacts));self.documents=set(documents);self.initial=None')
s=s.replace("            artifacts.extend(value.get('artifacts',[]))","""            artifacts.extend(value.get('artifacts',[]))
            if kind=='rights':artifacts.append(value['evidence_artifact'])
            for adoption in value.get('adoptions',[]):todo.append(('adoption',adoption['id']))""")
s=s.replace('        document_ids=set()','        document_ids=set(self.documents)\n        for kind,name in seen:\n            if kind==\'rights\':document_ids.add(repo.raw(kind,name)[\'parent_id\'])')
s=s.replace("scopes={('Project',self.project)}", "scopes={(self.scope_type,self.project)}")
s=s.replace('    def hold(self,actor):','''    def hold(self,actor,result=None):
        if result is not None:
            original=for_result(self.company,self.project,result,scope_type=self.scope_type)
            if original is not None:
                with original.hold(actor):yield
                return''')
start=s.index('def for_payload(');s=s[:start]+'''def for_payload(company,project,name,payload):
    if name=='clause.reference':return DocumentContext(company,project,[('adoption',payload['adoption_id'])],[payload['target']])
    if name=='redline.propose':return DocumentContext(company,project,[('clause_use',payload['clause_use_id'])])
    if name in ('shared.adoption.prepare','adoption.prepare'):return DocumentContext(company,project,[('library_revision',payload['library_revision'])])
    if name=='issue.prepare':return DocumentContext(company,project,[('adoption',r['id']) for r in payload['adoptions']],artifacts=payload['artifacts'])
    if name=='transmittal.prepare':return DocumentContext(company,project,[('issue',payload['issue_id'])])
    if name=='evidence.report':return DocumentContext(company,project,[(payload['subject_kind'],payload['subject_id'])],artifacts=payload['artifacts'])
    if name=='rights.record':return DocumentContext(company,project,artifacts=[payload['definition']['evidence_artifact']],documents=[payload['document_id']])
    if name in ('library.create','library.revise'):return DocumentContext(company,project,[('library',payload['library_id'])] if payload.get('library_id') else (),artifacts=[payload['artifact']])
    return None

def for_approval(company,project,payload):
    import frappe
    action=payload.get('action');subject=payload.get('subject_id')
    if payload.get('packet_id'):
        packet=frappe.get_doc('Cipher Approval Packet',payload['packet_id'])
        if packet.company!=company or packet.project!=project:return None
        action,subject=packet.action,packet.subject_id
    if action in rules.ACTIONS.values():return DocumentContext(company,project,[(next(k for k,v in rules.ACTIONS.items() if v==action),subject)])
    return None

def for_result(company,project,result,*,scope_type='Project'):
    roots=[]
    def visit(value):
        if type(value) is not dict:return
        for kind in rules.KINDS:
            row=value.get(kind)
            if type(row) is dict and row.get('id') and kind!='library':roots.append((kind,row['id']))
        if value.get('schema')=='cipher.document.approval.v1' and value.get('action') in rules.ACTIONS.values():roots.append((next(k for k,v in rules.ACTIONS.items() if v==value['action']),value['subject']['id']))
        for child in value.values():
            if type(child) is dict:visit(child)
    visit(result)
    return DocumentContext(company,project,roots,scope_type=scope_type) if roots else None
''';p.write_text(s)
p=r/'governance/commands.py';s=p.read_text().replace('participant_people=(), draft_save=None):','participant_people=(), draft_save=None, document_context=None):',1).replace('participant_people=participant_people, draft_save=draft_save)','participant_people=participant_people, draft_save=draft_save, document_context=document_context)',1)
s=s.replace('(document_context.hold(actor) if document_context is not None else nullcontext()):\n            authorize_receipt','(document_context.hold(actor,result) if document_context is not None else nullcontext()):\n            authorize_receipt',1)
s=s.replace("    if scope_type=='Project':\n        from cipher_aec.document_control.locking import for_result\n        context=for_result(company,project,result)","    if scope_type in ('Project','Company'):\n        from cipher_aec.document_control.locking import for_result\n        context=for_result(company,project,result,scope_type=scope_type)",1)
s=s.replace('        elif command.startswith("document."):', '''        elif command.startswith("document.control."):
            from cipher_aec.document_control.shared import authorize_receipt as authorize_documentary
            authorize_documentary(actor,company,result,lock=True)
        elif command.startswith("document."):''',1)
p.write_text(s)
# Retain source snapshot-specific Company history rather than reading later heads.
p=r/'governance/history_access.py';s=p.read_text();a=s.index('        from cipher_aec.document_control.contracts');b=s.index('        if subject',a+20);print(s[a:a+1100]);p.write_text(s)
# Test doubles must be scoped to their fixture; no lingering prior actor in new helper imports.
p=r/'tests/test_document_control.py';s=p.read_text();s=s.replace("('contracts','repository','rights','service','governance')", "('contracts','repository','rights','service','governance','clauses','locking','scopes','shared')",1).replace('for n in names];state.duties', 'for n in names[:5]];state.duties',1);p.write_text(s)
