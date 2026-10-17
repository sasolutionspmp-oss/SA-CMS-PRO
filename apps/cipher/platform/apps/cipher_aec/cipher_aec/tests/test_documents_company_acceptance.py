"""Opt-in native Company source acceptance; reuses a private committed COM identity.

No User/Auth writes, main fixture changes or new source storage adapter.
"""
from uuid import uuid4


def run_company_document_acceptance(user='commercial.fixture.fd89ca080f@cipher.example'):
    import frappe
    from cipher_aec.api.errors import DomainError
    from cipher_aec.governance.context import assert_synthetic_site, current_actor, duty_rows, trusted_write
    from cipher_aec.governance.commands import read_company_operation
    from cipher_aec.install import _grant_company
    from cipher_aec.documents import service
    from cipher_aec.documents.extraction import digest
    from cipher_aec.tests.test_documents import pdf_bytes
    assert_synthetic_site()
    if frappe.session.user!='Administrator' or not user.startswith('commercial.fixture.'):
        raise RuntimeError('Explicit isolated fixture Administrator context is required')
    for doctype in ('Cipher Document','Cipher Document Revision'):
        if not frappe.db.has_column(doctype,'scope_type'):
            raise RuntimeError('Company Document metadata must migrate before fixture writes')
    person=frappe.db.get_value('Cipher Identity Binding',{'user':user,'active':1},'person')
    if not person or not person.startswith('COM-FIXTURE-'):
        raise RuntimeError('Only an isolated committed COM fixture identity is accepted')
    company=frappe.db.get_value('Cipher Project Duty',{'person':person,'scope_type':'Company','ability':'company.read','active':1},'company')
    if not company or not company.startswith('COM-01 isolated company '):
        raise RuntimeError('The isolated Company fixture must be configured explicitly')
    alias='commercial.alias.'+user.split('@')[0].rsplit('.',1)[1]+'@cipher.example'
    with trusted_write():
        for ability in ('document.read','document.write'):_grant_company(person,company,ability)
    frappe.db.commit()
    checks=[]
    def reject(name,callback,codes):
        try:callback()
        except DomainError as error:
            assert error.code in codes,(name,error.code)
            checks.append({'check':name,'status':'passed','error_code':error.code})
        else:raise AssertionError('Expected current source rejection: '+name)
    marker=uuid4().hex[:10]
    content=pdf_bytes(['Synthetic Company concrete strength 4500 psi '+marker,'Exact retained page citation '+marker])
    payload={'company':company,'title':'Synthetic Company canonical source '+marker,'filename':'company-source.pdf','content':content,'byte_length':len(content),'sha256':digest(content),'operation_id':str(uuid4())}
    frappe.set_user(user)
    try:
        assert not duty_rows(current_actor())
        before=frappe.db.count('Cipher Document',{'company':company,'scope_type':'Company'})
        result=service.upload_company_document(**payload)
        docid,rid=result['document']['id'],result['revision']['id']
        assert result['document']['scope_type']=='Company' and result['document']['project'] is None
        row=frappe.db.get_value('Cipher Document Revision',rid,['scope_type','project','storage_reference'],as_dict=True)
        assert row.scope_type=='Company' and row.project is None
        file=frappe.get_doc('File',row.storage_reference)
        assert file.is_private and file.attached_to_name==rid
        citation=service.get_company_citation(company,rid,2)
        assert marker in citation['excerpt'] and citation['source_sha256']==digest(content)
        assert service.download_company_revision(company,rid)[1]==content
        assert service.preview_company_revision(company,rid,2)['content_type']=='text/plain'
        assert service.search_company_documents(company,'4500')[0]['revision_id']==rid
        assert service.company_source_reference(company,rid,2,lock=True)['is_current']
        checks.append({'check':'company_only_pdf_exact_bytes_page_citation_preview_search_native_private_file','status':'passed'})
        frappe.set_user(alias)
        replay=service.upload_company_document(**payload)
        assert replay['operation']['replayed'] and replay['revision']['id']==rid
        assert frappe.db.count('Cipher Document',{'company':company,'scope_type':'Company'})==before+1
        assert frappe.db.count('Cipher Document Revision',{'document':docid})==1
        assert read_company_operation(company,payload['operation_id'])['revision']['id']==rid
        checks.append({'check':'canonical_alias_receipt_replay_one_document_one_revision','status':'passed'})
        reject('project_reader_never_widens_to_company',lambda:service.get_citation(company,rid,2),{'not_found'})
        newcontent=('Synthetic Company current strength 5000 psi '+marker).encode()
        successor={**payload,'filename':'company-source.txt','content':newcontent,'byte_length':len(newcontent),'sha256':digest(newcontent),'document_id':docid,'expected_revision':1,'operation_id':str(uuid4())}
        second=service.upload_company_document(**successor)
        assert service.get_company_citation(company,rid,2)==citation
        assert not service.company_source_reference(company,rid,2,lock=True)['is_current']
        assert service.company_source_reference(company,second['revision']['id'],1,lock=True)['is_current']
        assert service.search_company_documents(company,'4500')==[]
        checks.append({'check':'immutable_retained_page_and_explicit_current_working_head','status':'passed'})
        reject('stale_company_head',lambda:service.upload_company_document(**{**successor,'operation_id':str(uuid4())}),{'revision_conflict'})
        doc=frappe.get_doc('Cipher Document',docid)
        doc.scope_type='Project';doc.project=frappe.db.get_value('Project',{},'name')
        try:
            with trusted_write():doc.save(ignore_permissions=True)
        except (frappe.ValidationError,ValueError):pass
        else:raise AssertionError('Canonical Company source ownership was rewritten')
        assert frappe.db.get_value('Cipher Document',docid,'scope_type')=='Company'
        assert frappe.db.get_value('Cipher Document',docid,'project') is None
        checks.append({'check':'scope_immutable_even_on_trusted_native_controller_save','status':'passed'})
        frappe.set_user('Administrator')
        with trusted_write():
            duty=frappe.get_doc('Cipher Project Duty',frappe.db.get_value('Cipher Project Duty',{'person':person,'company':company,'scope_type':'Company','ability':'document.read'},'name'))
            duty.active=0;duty.save(ignore_permissions=True)
        frappe.set_user(user)
        for name,callback in (
            ('revoked_company_document_receipt',lambda:read_company_operation(company,payload['operation_id'])),
            ('revoked_company_document_replay',lambda:service.upload_company_document(**payload)),
            ('revoked_company_document_new_upload',lambda:service.upload_company_document(**{**payload,'operation_id':str(uuid4())})),
            ('revoked_company_document_citation',lambda:service.get_company_citation(company,rid,2))):
            reject(name,callback,{'capability_denied','not_found'})
        frappe.set_user('Administrator')
        with trusted_write():duty.active=1;duty.save(ignore_permissions=True)
        frappe.db.commit()
        return {'schema':'cipher.company-document.native-acceptance.v1','status':'passed','company':company,'user':user,'alias':alias,'project':None,'document_id':docid,'original_revision':rid,'current_revision':second['revision']['id'],'source_sha256':digest(content),'citation_id':citation['id'],'checks':checks,'credentials_recorded':False,'qualification_limits':['Explicit synthetic allow-unscanned policy; no antivirus or OCR claim.','Same Frappe private File authority; native HTTP/private URL closure is qualified separately by independent integration QA.']}
    finally:
        frappe.db.rollback();frappe.set_user('Administrator')


def resolver_readback(user='commercial.fixture.fd89ca080f@cipher.example'):
    """Read-only native resolver qualification against the same committed masters."""
    import frappe
    from cipher_aec.governance.context import assert_synthetic_site,current_actor,duty_rows
    from cipher_aec.migrations.export import FrappeCompanyTargetReader
    assert_synthetic_site()
    if frappe.session.user!='Administrator' or not user.startswith('commercial.fixture.'):
        raise RuntimeError('Explicit isolated fixture context is required')
    marker=user.split('@')[0].rsplit('.',1)[1];company='COM-01 isolated company '+marker
    frappe.set_user(user)
    try:
        assert not duty_rows(current_actor())
        reader=FrappeCompanyTargetReader(company)
        assert reader.fetch('company',company).name==company
        assert reader.fetch('project',frappe.db.get_value('Project',{},'name')) is None
        # This native Customer intentionally has no Company account association.
        # Commercial's explicit Pursuit link and MIG/EST master association are
        # different references; no absent Project supplies a customer exception.
        customer='COM-01 isolated customer '+marker
        assert frappe.has_permission('Customer','read',doc=customer,user=user)
        assert reader.fetch('customer',customer) is None
        unit=reader.fetch('uom','COM-01 qualified unit '+marker)
        assert unit.cipher_unit_id and unit.cipher_unit_revision==1
        export_allowed=bool(frappe.has_permission('UOM','export',doc=unit,user=user))
        assert (reader.fetch('uom',unit.name,for_export=True) is not None)==export_allowed
        return {'status':'passed','company':company,'checks':{'current_company_native_read':True,'company_never_resolves_project':True,'native_read_unassociated_customer_denied':True,'qualified_unit_identity_reused':True,'export_matches_current_native_permission':True},'native_unit_export_allowed':export_allowed,'writes_performed':0}
    finally:frappe.set_user('Administrator')
