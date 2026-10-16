"""Current party/source rights and conservative initial-activity admission."""
import frappe
from cipher_aec.api.contracts import digest, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.migrations.export import FrappeTargetReader

ADMISSION_VERSION = 'cipher.contract.new-native-admission.v1'
# These native channels are supported by the installed stack. In the absence of
# contract linkage, activity for this company/counterparty is conservatively
# unqualified even when it might actually belong to another project.
PARTY_CHANNELS = {'Customer': (('Sales Order', 'customer'), ('Sales Invoice', 'customer'), ('Delivery Note', 'customer')),
                 'Supplier': (('Purchase Order', 'supplier'), ('Purchase Invoice', 'supplier'), ('Purchase Receipt', 'supplier'))}
FUTURE_CHANNELS = ('Cipher Commitment', 'Cipher Installed Work Certificate', 'Cipher Sub Pay Application',
                   'Cipher Owner Billing Application', 'Cipher Retainage Movement', 'Cipher Stored Material Lot')


def party_snapshot(company, project, definition, actor, *, lock=False, allow_disabled=False):
    native = FrappeTargetReader(company, project, actor=actor).fetch(definition['party_type'].lower(), definition['party'], lock=lock)
    if native is None:
        raise DomainError('not_found', 'This native counterparty is not available in the current scope.', 404)
    if native.get('disabled') and not allow_disabled:
        raise DomainError('counterparty_disabled', 'An enabled native counterparty is required for new contract effects.', 409)
    return {'doctype': native.doctype, 'name': native.name, 'version': version_of(native), 'disabled': bool(native.get('disabled'))}


def admission(contract, *, lock=False):
    """Never infer contract-specific zero from unlinked party/project activity.

    Use current locking SQL when preparing/consuming approval. Retain exact
    provenance and bounded identities rather than a misleading zero balance.
    """
    suffix = ' FOR UPDATE' if lock else ''
    found, channels, recognized = [], [], []
    def bounded(query,args,**kwargs):
        rows=frappe.db.sql(query,args,**kwargs)
        if len(rows)>200:raise DomainError('admission_scan_limit','Narrow this native activity scope before admission.',409)
        return rows
    for doctype, field in PARTY_CHANNELS[contract['definition']['party_type']]:
        channels.append(doctype)
        rows = bounded(f'SELECT name,docstatus,modified FROM `tab{doctype}` WHERE company=%s AND `{field}`=%s ORDER BY name LIMIT 201' + suffix,
                             (contract['company'], contract['definition']['party']), as_dict=True)
        if doctype == 'Sales Order' and frappe.db.exists('DocType','Cipher Award Adoption'):
            from .award_admission import recognize_award_sales_order,inspect_award_sales_order
            classify=recognize_award_sales_order if lock else inspect_award_sales_order
            unqualified=[]
            for row in rows:
                # Current native Customer scope was locked by the consequential
                # caller before this scan. No foreign canonical source locks.
                proof=classify(company=contract['company'],customer=contract['definition']['party'],sales_order_id=row.name,own_contract_id=contract['id'])
                if proof['classification']=='unqualified':unqualified.append(row)
                else:recognized.append({'native':row.name,**proof})
            rows=unqualified
        found.extend({'doctype': doctype, 'name': r.name, 'docstatus': r.docstatus, 'version': version_of(r), 'association': 'company_counterparty_without_qualified_contract_link'} for r in rows)
    # Payment and journal channels can carry project obligations without a direct
    # contract reference. This deliberately blocks ambiguous pre-existing activity.
    channels.append('Payment Entry')
    rows = bounded('SELECT name,docstatus,modified FROM `tabPayment Entry` WHERE company=%s AND party_type=%s AND party=%s ORDER BY name LIMIT 201' + suffix,
                         (contract['company'], contract['definition']['party_type'], contract['definition']['party']), as_dict=True)
    found.extend({'doctype': 'Payment Entry', 'name': r.name, 'docstatus': r.docstatus, 'version': version_of(r), 'association': 'company_counterparty_without_qualified_contract_link'} for r in rows)
    channels.append('Journal Entry')
    rows = bounded('SELECT DISTINCT p.name,p.docstatus,p.modified FROM `tabJournal Entry` p JOIN `tabJournal Entry Account` a ON a.parent=p.name WHERE p.company=%s AND (a.project=%s OR (a.party_type=%s AND a.party=%s)) ORDER BY p.name LIMIT 201' + suffix,
                         (contract['company'], contract['project'], contract['definition']['party_type'], contract['definition']['party']), as_dict=True)
    found.extend({'doctype': 'Journal Entry', 'name': r.name, 'docstatus': r.docstatus, 'version': version_of(r), 'association': 'project_or_counterparty_without_qualified_contract_link'} for r in rows)
    for doctype in ('Stock Entry', 'Expense Claim', 'Timesheet', 'Material Request'):
        if not frappe.db.exists('DocType', doctype):
            channels.append(doctype + ':not_installed')
            continue
        channels.append(doctype)
        meta = frappe.get_meta(doctype)
        project_paths = []
        if meta.has_field('project'):
            project_paths.append(('parent', None))
        for field in meta.fields:
            if field.fieldtype == 'Table' and frappe.get_meta(field.options).has_field('project'):
                project_paths.append(('child', field.options))
        if not project_paths:
            # A company-only channel cannot prove that existing activity belongs
            # to a different contract. Treat every such row as ambiguous.
            rows = bounded(f'SELECT name,docstatus,modified FROM `tab{doctype}` WHERE company=%s ORDER BY name LIMIT 201' + suffix, (contract['company'],), as_dict=True)
        else:
            rows = []
            for source, child in project_paths:
                if source == 'parent':
                    rows.extend(bounded(f'SELECT name,docstatus,modified FROM `tab{doctype}` WHERE company=%s AND project=%s ORDER BY name LIMIT 201' + suffix,
                                              (contract['company'], contract['project']), as_dict=True))
                else:
                    rows.extend(bounded(f'SELECT DISTINCT p.name,p.docstatus,p.modified FROM `tab{doctype}` p JOIN `tab{child}` c ON c.parent=p.name AND c.parenttype=%s WHERE p.company=%s AND c.project=%s ORDER BY p.name LIMIT 201' + suffix,
                                              (doctype, contract['company'], contract['project']), as_dict=True))
        if len({r.name for r in rows})>200:raise DomainError('admission_scan_limit','Narrow this native activity scope before admission.',409)
        found.extend({'doctype': doctype, 'name': r.name, 'docstatus': r.docstatus, 'version': version_of(r), 'association': 'conservative_project_activity_not_certified_floor_authority'} for r in {r.name:r for r in rows}.values())
    for doctype in FUTURE_CHANNELS:
        if not frappe.db.exists('DocType', doctype):
            channels.append(doctype + ':not_installed')
            continue
        channels.append(doctype)
        if not frappe.get_meta(doctype).has_field('contract'):
            raise DomainError('activity_unqualified', 'An installed obligation channel lacks qualified contract linkage.', 409, {'channel': doctype})
        rows = bounded(f'SELECT name,modified FROM `tab{doctype}` WHERE contract=%s ORDER BY name LIMIT 201' + suffix, (contract['id'],), as_dict=True)
        found.extend({'doctype': doctype, 'name': r.name, 'version': version_of(r), 'association': 'contract'} for r in rows)
    result = {'provider': ADMISSION_VERSION, 'provider_version': 1, 'contract_id': contract['id'], 'company': contract['company'], 'project': contract['project'],
              'party_type': contract['definition']['party_type'], 'party': contract['definition']['party'], 'channels': channels,
              'status': 'new_contract_without_supported_obligations' if not found else 'activity_unqualified', 'observed': found}
    provider=ADMISSION_VERSION
    if recognized:
        provider='cipher.contract.award-native-admission.v1'
        result['recognized_award_observations']=recognized
        result['provider']=provider
        if not found:result['status']='qualified_award_obligations' if any(row['classification']=='recognized-own' for row in recognized) else 'qualified_award_observations'
    # Native financial identities are not authorized by counterparty/project
    # read. Bind the private scan transiently, and expose only opaque admission.
    watermark = digest(result)
    return {'provider': provider, 'provider_version': 1, 'contract_id': contract['id'],
            'status': result['status'], 'channel_count': len(channels), 'source_watermark': watermark}


def require_initial_admission(contract, *, lock=False):
    initial = contract.get('creation_admission', {})
    current = admission(contract, lock=lock)
    if contract.get('origin')=='governed_award_v1':
        # Initial award provenance is never a zero/floor or activation grant.
        # Only this fresh complete committed recognition admits the draft's
        # registered obligation; all other/ambiguous activity still refuses.
        from .award_admission import INITIAL_PROVIDER
        if (initial.get('provider')!=INITIAL_PROVIDER or initial.get('status')!='qualified_award_draft_obligation'
                or current['provider']!='cipher.contract.award-native-admission.v1' or current['status']!='qualified_award_obligations'):
            raise DomainError('activity_unqualified','The exact committed award obligation and independent grant cannot be verified.',409)
        return current
    if contract.get('origin') != 'server_created_fin01' or initial.get('provider') not in {ADMISSION_VERSION,'cipher.contract.award-native-admission.v1'} or initial.get('status') not in {'new_contract_without_supported_obligations','qualified_award_observations'} or current['status'] not in {'new_contract_without_supported_obligations','qualified_award_observations'}:
        raise DomainError('activity_unqualified', 'Initial activation requires a server-created contract with no supported obligations. Existing or ambiguous native activity requires a qualified floor reader.', 409)
    return current
