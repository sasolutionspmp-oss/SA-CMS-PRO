"""Opaque award lineage classification; it never grants foreign-source access.

The consequential entry requires its caller already hold the exact canonical
Customer row FOR UPDATE. Only the native order observation may take new locks.
Canonical immutable lineage reads are ordinary reads: an older RR snapshot that
cannot see newly committed evidence refuses/retries rather than inverting locks
against foreign Company/Project/receipt/source transactions.
"""
import json
import frappe
from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError

INITIAL_PROVIDER='cipher.award.initial-draft-obligation.v1'
ORIGIN='governed_award_v1'


def _canonical(doctype,name):
    if not name:return None
    rows=frappe.db.sql('SELECT data_json,record_digest FROM `tab'+doctype+'` WHERE name=%s',(name,))
    if len(rows)!=1:return None
    try:value=json.loads(rows[0][0])
    except (ValueError,TypeError):return None
    return value if type(value) is dict and value.get('id')==name and digest(value)==rows[0][1] else None


def _row(doctype,name):
    rows=frappe.db.sql('SELECT * FROM `tab'+doctype+'` WHERE name=%s',(name,),as_dict=True)
    return dict(rows[0]) if len(rows)==1 else None


def observe(*,company,customer,sales_order_id,lock=False):
    """Private snapshot acquisition; no actor, source authorization or late masters."""
    from cipher_aec.awards import native
    rows=frappe.db.sql('SELECT name,record_digest FROM `tabCipher Award Adoption` WHERE company=%s AND sales_order=%s LIMIT 2',(company,sales_order_id))
    if len(rows)!=1:return {'native_id':sales_order_id,'adoption':None}
    adoption=_canonical('Cipher Award Adoption',rows[0][0])
    if adoption is None:return {'native_id':sales_order_id,'adoption':None}
    try:order=native.snapshot(sales_order_id=sales_order_id,lock=lock)
    except frappe.DoesNotExistError:return {'native_id':sales_order_id,'adoption':None}
    plan=_canonical('Cipher Award Handoff Revision',adoption.get('award_revision'))
    handoff=_canonical('Cipher Award Handoff',adoption.get('handoff'))
    contract=_canonical('Cipher Construction Contract',adoption.get('contract'))
    issue=_canonical('Cipher Proposal Issue',adoption.get('issue'))
    baseline=_canonical('Cipher Estimate Acceptance',(adoption.get('accepted_estimate') or {}).get('acceptance_id'))
    profile=_canonical('Cipher Project Profile',adoption.get('profile'))
    lines=frappe.db.sql('SELECT name FROM `tabCipher Award Line Adoption` WHERE handoff=%s ORDER BY name LIMIT 151',(adoption.get('handoff'),))
    if len(lines)>150:raise DomainError('admission_scan_limit','Award lineage exceeds its qualified bounded scope.',409)
    line_values=[_canonical('Cipher Award Line Adoption',row[0]) for row in lines]
    packet=_row('Cipher Approval Packet',adoption.get('packet_id'))
    decision=_row('Cipher Approval Decision',adoption.get('decision_id'))
    consumption_rows=frappe.db.sql('SELECT * FROM `tabCipher Approval Consumption` WHERE packet=%s LIMIT 2',(adoption.get('packet_id'),),as_dict=True)
    receipt=_row('Cipher Command Receipt',digest({'person':adoption.get('author_person'),'operation_id':adoption.get('operation_id')}))
    project_rows=frappe.db.sql('SELECT name,company,customer FROM `tabProject` WHERE name=%s',(adoption.get('target_project'),))
    project={'name':project_rows[0][0],'company':project_rows[0][1],'customer':project_rows[0][2]} if len(project_rows)==1 else None
    return {'native_id':sales_order_id,'project':project,'adoption':adoption,'plan':plan,'handoff':handoff,'contract':contract,'issue':issue,
        'baseline':baseline,'profile':profile,'lines':line_values,'order':order,'packet':packet,'decision':decision,
        'consumption':dict(consumption_rows[0]) if len(consumption_rows)==1 else None,'receipt':receipt}


def classify(snapshot,*,company,customer,own_contract_id=None):
    """Pure exact predicate over separately acquired snapshots, no database access."""
    from cipher_aec.awards import native
    try:
        a,p,h,c,i,b,f=(snapshot[k] for k in ('adoption','plan','handoff','contract','issue','baseline','profile'))
        real_project=snapshot['project']
        if type(real_project) is not dict or real_project.get('name')!=a['target_project'] or real_project.get('company')!=company or real_project.get('customer')!=customer:return 'unqualified'
        order=snapshot['order'];packet=snapshot['packet'];decision=snapshot['decision'];consumption=snapshot['consumption'];receipt=snapshot['receipt']
        if any(type(v) is not dict for v in (a,p,h,c,i,b,f,order,packet,decision,consumption,receipt)):return 'unqualified'
        if (a['schema']!='cipher.award.adoption.v1' or a['status']!='adopted' or a['scope_type']!='Company' or a['project'] is not None
                or a['company']!=company or a['sales_order']!=snapshot['native_id'] or a['sales_order']!=order['projection']['header']['name'] or p['company']!=company or h['company']!=company
                or a['id']!=p['ids']['adoption_id'] or a['contract']!=p['ids']['contract_id'] or a['profile']!=p['ids']['profile_id']
                or h.get('status')!='adopted' or h.get('adoption')!=a['id'] or p['id']!=a['award_revision'] or p['handoff']!=h['id'] or h['id']!=a['handoff'] or a['plan_digest']!=digest(p)
                or any(a[k]!=h[k] for k in ('pursuit','opportunity')) or a['issue']!=p['issue'] or a['issue_digest']!=p['issue_digest']
                or a['author_person']!=p['author_person'] or a['accepted_estimate']!=p['source_facts']['accepted_estimate']):return 'unqualified'
        if (i['id']!=a['issue'] or i['company']!=company or digest(i)!=a['issue_digest'] or i['accepted_estimate']!=a['accepted_estimate']
                or b['company']!=company or b['scope_type']!='Company' or b['project'] is not None or b['status']!='accepted'
                or b['id']!=a['accepted_estimate']['acceptance_id'] or digest(b)!=a['accepted_estimate']['acceptance_digest']):return 'unqualified'
        origin=c['award_origin']
        if (c['id']!=a['contract'] or c['origin']!=ORIGIN or c['company']!=company or c['project']!=a['target_project']
                or c['definition']!=p['definition']['contract_definition'] or c['definition']['party_type']!='Customer' or c['definition']['party']!=customer
                or origin['handoff']!=h['id'] or origin['award_revision']!=p['id'] or origin['plan_digest']!=digest(p)
                or origin['adoption_id']!=a['id'] or origin['sales_order']!=a['sales_order'] or origin['native_digest']!=a['native_digest']
                or origin['native_version']!=a['native_version'] or origin['issue']!=a['issue'] or origin['issue_digest']!=a['issue_digest']
                or origin['accepted_estimate']!=a['accepted_estimate'] or origin['source_company']!=company or origin['project']!=a['target_project']
                or origin['definition_digest']!=digest(c['definition']) or c['creation_admission']['provider']!=INITIAL_PROVIDER
                or any(origin[k]!=a[k] for k in ('packet_id','decision_id','operation_id'))):return 'unqualified'
        if (f['id']!=a['profile'] or f['status']!='adopted' or f['company']!=company or f['project']!=a['target_project'] or f['handoff']!=h['id']
                or f['award_revision']!=p['id'] or f['adoption']!=a['id'] or f['contract']!=c['id'] or f['sales_order']!=a['sales_order']):return 'unqualified'
        actual=native.reconcile(order,company=company,project=a['target_project'],award_id=h['id'],issue=i,lines=p['lines'],definition=p['definition']['native_order_definition'])
        if order!=a['native_snapshot'] or actual!=a['native_digest'] or order['derived_digest']!=actual or order['version']!=a['native_version']:return 'unqualified'
        lines=snapshot['lines'];expected={row['award_line_id']:row for row in p['lines']}
        native_rows={row['cipher_award_line_id']:row for row in order['projection']['rows']}
        if len(lines)!=len(expected) or len({row['id'] for row in lines})!=len(expected) or set(a['line_adoptions'])!=set(expected):return 'unqualified'
        for row in lines:
            line=expected.get(row['id']);native_row=native_rows.get(row['id'])
            if line is None or native_row is None or row['source_line']!=line or row['proposal_line_id']!=line['proposal_line_id'] or row['sales_order_item']!=native_row['name'] or row['adoption']!=a['id'] or row['id']!=p['ids']['line_ids'].get(line['proposal_line_id']):
                return 'unqualified'
            if any(row[key]!=a[key] for key in ('company','target_project','handoff','award_revision','pursuit','opportunity','issue','issue_digest','sales_order','contract','author_person')):return 'unqualified'
        outer=json.loads(packet['manifest_json'])
        if (packet['manifest_hash']!=digest(outer) or packet['action']!='award.project.create.v1' or packet['scope_type']!='Company' or packet.get('project')
                or packet['company']!=company or packet['subject_id']!=p['id'] or packet['subject_type']!='Cipher Award Handoff Revision'
                or packet['source_version']!=digest(p) or packet['requester_person']!=a['author_person'] or outer['domain']['effect']['plan']!=p
                or decision['decision']!='Grant' or decision['packet']!=packet['name'] or decision['manifest_hash']!=packet['manifest_hash']
                or decision['actor_person']==packet['requester_person'] or decision['company']!=company or decision['scope_type']!='Company' or decision.get('project')
                or consumption['company']!=company or consumption['scope_type']!='Company' or consumption.get('project')
                or consumption['decision']!=decision['name'] or consumption['packet']!=packet['name'] or consumption['actor_person']!=a['author_person']
                or consumption['operation_id']!=a['operation_id']):return 'unqualified'
        effect={'adoption':a,'version':digest(a)}
        result=json.loads(receipt['result_json'])
        expected_request=digest({'scope_type':'Company','command':'approval.execute','company':company,'project':None,
            'payload':{'packet_id':packet['name'],'manifest_hash':packet['manifest_hash']}})
        if (consumption['result_hash']!=digest(effect) or receipt['person']!=a['author_person'] or receipt['operation_id']!=a['operation_id']
                or receipt['scope_type']!='Company' or receipt.get('project') or receipt['company']!=company or receipt['command']!='approval.execute'
                or receipt['request_hash']!=expected_request or receipt['result_hash']!=digest(result) or result['effect']!=effect
                or result['packet']['id']!=packet['name'] or result['packet']['manifest_hash']!=packet['manifest_hash'] or result['packet']['state']!='Consumed'):return 'unqualified'
        return 'recognized-own' if c['id']==own_contract_id else 'recognized-other'
    except (KeyError,TypeError,ValueError,AttributeError,DomainError):return 'unqualified'


def _result(snapshot,company,customer,own_contract_id):
    classification=classify(snapshot,company=company,customer=customer,own_contract_id=own_contract_id)
    a=snapshot.get('adoption') or {};order=snapshot.get('order') or {}
    return {'classification':classification,'watermark':digest({'classification':classification,'adoption_digest':digest(a),
        'native_digest':order.get('digest'),'native_version':order.get('version'),'contract_origin':(snapshot.get('contract') or {}).get('award_origin'),
        'line_digests':[digest(row) for row in snapshot.get('lines',[])],'receipt_hash':(snapshot.get('receipt') or {}).get('result_hash')})}


def recognize_award_sales_order(*,company,customer,sales_order_id,own_contract_id=None):
    """PRIVATE: caller already holds canonical Customer FOR UPDATE; no late masters."""
    return _result(observe(company=company,customer=customer,sales_order_id=sales_order_id,lock=True),company,customer,own_contract_id)


def inspect_award_sales_order(*,company,customer,sales_order_id,own_contract_id=None):
    """Read-only observation only; never claims consequential admission or a lock."""
    return _result(observe(company=company,customer=customer,sales_order_id=sales_order_id,lock=False),company,customer,own_contract_id)
