"""Bounded native draft Sales Order adapter for the registered award effect.

No mapper, submission or generic writer exception lives here. Resource planning
is discovery only; the caller acquires its entire Issue/award/native union first.
"""
from decimal import Decimal

import frappe

from cipher_aec.api.contracts import digest, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.commercial import native as commercial
from cipher_aec.commercial.contracts import business_date, decimal, identifier, keys
from cipher_aec.documents.provenance import is_prelocked
from cipher_aec.estimating import units
from cipher_aec.governance.context import require_company

POLICY = 'cipher.award.sales_order.reconciliation.v1'
PAYMENT_POLICY = 'native-default-100-percent-transaction-date-v1'
PAYMENT_TEXT = ('name','payment_term','description','due_date','mode_of_payment','discount_date',
    'discount_type','due_date_based_on','discount_validity_based_on')
PAYMENT_NUMBERS = ('invoice_portion','payment_amount','base_payment_amount','paid_amount','base_paid_amount',
    'discounted_amount','outstanding','base_outstanding','discount','credit_days','credit_months','discount_validity')
HEADER_NUMBERS = ('conversion_rate','plc_conversion_rate','total','net_total','grand_total','rounded_total',
    'base_total','base_net_total','base_grand_total','base_rounded_total','total_taxes_and_charges',
    'discount_amount','additional_discount_percentage')
HEADER_TEXT = ('name','company','project','customer','transaction_date','delivery_date','currency',
    'selling_price_list','price_list_currency','apply_discount_on','cipher_award_handoff','cipher_issue',
    'cipher_issue_digest','cipher_proposal_revision','cipher_accepted_baseline','payment_terms_template')
ROW_NUMBERS = ('qty','conversion_factor','rate','amount','base_rate','base_amount','discount_percentage','discount_amount')
ROW_TEXT = ('name','cipher_award_line_id','cipher_proposal_line_id','item_code','description','uom','stock_uom',
    'delivery_date','prevdoc_docname','quotation_item')
SOURCE_LINKS = ('cipher_award_handoff','cipher_issue','cipher_issue_digest','cipher_proposal_revision',
    'cipher_accepted_baseline','cipher_award_native_digest')


def _fail(message, code='native_award_reconciliation', status=422):
    raise DomainError(code, message, status)


def _definition(definition, lines):
    keys(definition, ('customer','transaction_date','delivery_date','selling_price_list'),
        ('customer','transaction_date','delivery_date','selling_price_list'))
    for field in ('customer','selling_price_list'):
        value=definition[field]
        if type(value) is not str or not value.strip() or len(value)>140 or any(ord(c)<32 for c in value):
            _fail('Select an existing Customer and selling Price List.')
    business_date(definition['transaction_date']);business_date(definition['delivery_date'])
    if type(lines) is not list or not 1<=len(lines)<=150:
        _fail('Adopt one through150 exact selected Issue lines.')
    seen, source_ids, currencies=set(),set(),set()
    for line in lines:
        fields=('award_line_id','proposal_line_id','description','item_code','quantity','rate','amount','unit','currency','conversion_factor','delivery_date')
        keys(line,fields,fields)
        identifier(line['award_line_id']);identifier(line['proposal_line_id'])
        if line['award_line_id'] in seen or line['proposal_line_id'] in source_ids:
            _fail('Stable award and proposal line identities must each be unique.')
        seen.add(line['award_line_id']);source_ids.add(line['proposal_line_id'])
        business_date(line['delivery_date'])
        if line['delivery_date']<definition['transaction_date']:
            _fail('Delivery cannot precede the native transaction date.')
        decimal(line['quantity'],positive=True);decimal(line['rate']);decimal(line['amount'])
        if line.get('conversion_factor')!={'numerator':'1','denominator':'1'}:
            _fail('This award adapter supports exact1:1 stock-UOM quantities only.')
        identifier(line['unit']['id'])
        if line['unit'].get('target',{}).get('doctype')!='UOM':
            _fail('Each line requires its exact qualified native UOM.')
        if type(line['item_code']) is not str or not line['item_code'].strip() or len(line['item_code'])>140:
            _fail('Each line requires an explicit existing sales Item.')
        currencies.add(line['currency'])
    if len(currencies)!=1 or definition['delivery_date']!=max(line['delivery_date'] for line in lines):
        _fail('The header must retain one exact currency and the latest selected delivery date.')
    return next(iter(currencies))


def _canonical_names(lines, definition):
    """Metadata discovery only, before names enter any sorted lock union."""
    refs={('Customer',definition['customer']),('Price List',definition['selling_price_list'])}
    refs.update(('Item',line['item_code']) for line in lines)
    for kind,name in refs:
        stored=frappe.db.get_value(kind,name,'name',cache=False)
        if stored!=name:
            _fail('An award native source is unavailable.','not_found',404)


def _required(lines, definition):
    currency=_definition(definition,lines)
    refs={('Customer',definition['customer']),('Price List',definition['selling_price_list'])}
    refs.update(('Item',line['item_code']) for line in lines)
    return {'unit_ids':sorted({line['unit']['id'] for line in lines}), 'currencies':[currency],
        'native_refs':[{'doctype':kind,'name':name} for kind,name in sorted(refs)],'generated_sources':[]}


def plan_resources(*, company, issue, lines, definition, actor, lock=False):
    """Discover own immutable references; caller separately authorizes the Issue."""
    from .contracts import selected_sales_lines
    if issue.get('company')!=company:
        _fail('The Issue belongs to a different Company.','not_found',404)
    expected=selected_sales_lines(issue,[{key:line[key] for key in ('proposal_line_id','item_code','delivery_date')}
        for line in lines],definition['transaction_date'])
    actual=sorted([{key:value for key,value in line.items() if key!='award_line_id'} for line in lines],key=lambda row:row['proposal_line_id'])
    if expected!=actual:
        _fail('The complete selected Issue facts must be adopted without substitution.')
    _canonical_names(lines,definition)
    return _required(lines,definition)


def _sets(plan):
    return (set(plan.get('unit_ids',[])),set(plan.get('currencies',[])),
        {(row['doctype'],row['name']) for row in plan.get('native_refs',[])},
        {(row['document_id'],row['input_digest']) for row in plan.get('generated_sources',[])})


def _require_token(required, token, actor, company):
    if (type(token) is not dict or not is_prelocked(token,actor,company)
            or any(not wanted<=held for wanted,held in zip(_sets(required),_sets(token)))):
        _fail('Acquire the complete current award resource union before native authorization.','source_prelock_required',409)


def authorize_sources(*, actor, company, lines, definition, resource_token, lock=False, for_new=True, require_create=True):
    """Reauthorize current sources; reviewer reads confer no creation authority.

    Historical reads retain current native scope/read and immutable UOM facts
    while allowing disabled originals. Only the actual new-use requester needs
    native create rights; the returned policy is identical for every actor.
    """
    required=_required(lines,definition)
    if lock:_require_token(required,resource_token,actor,company)
    company_doc=require_company(company,ability='commercial.read',actor=actor,lock=lock)
    if require_create:
        require_company(company,ability='commercial.award',actor=actor,lock=lock)
        commercial.can_create('Project',actor);commercial.can_create('Sales Order',actor)
    qualified={name:units.qualified(name,lock=lock,allow_disabled=not for_new,actor=actor) for name in required['unit_ids']}
    currency=required['currencies'][0]
    if for_new:
        policy=units.currency_policy(currency,lock=lock,actor=actor)
    else:
        original_currency=commercial.require_native('Currency',currency,actor,lock=lock)
        policy={'currency':currency,'native_currency_version':version_of(original_currency)}
    if for_new and company_doc.default_currency!=currency:
        _fail('Native award drafts currently require the Company base currency.','unsupported_award_currency')
    from cipher_aec.migrations.export import FrappeCompanyTargetReader
    reader=FrappeCompanyTargetReader(company,actor=actor,ability='commercial.read')
    native={}
    for row in required['native_refs']:
        kind,name=row['doctype'],row['name']
        record=reader.fetch(kind.lower(),name,lock=lock) if kind in {'Customer','Item'} else commercial.require_native(kind,name,actor,lock=lock)
        if record is None or record.name!=name:_fail('An award native source is unavailable in this Company.','not_found',404)
        native[(kind,name)]=record
        if for_new and kind=='Customer' and (record.get('disabled') or record.get('is_internal_customer')):
            _fail('This bounded award requires an active external Customer.')
        if for_new and kind=='Item' and (record.get('disabled') or not record.get('is_sales_item') or record.get('is_stock_item')
                or record.get('has_variants') or record.get('is_fixed_asset') or record.get('is_sub_contracted_item')):
            _fail('Only enabled nonstock sales Items without unsupported stock/asset/subcontract behavior are qualified.')
        if for_new and kind=='Price List' and (not record.get('enabled') or not record.get('selling') or record.get('currency')!=currency):
            _fail('Select an enabled selling Price List in the exact base currency.')
    for line in lines:
        unit=qualified[line['unit']['id']]
        if unit!=line['unit']:
            _fail('The issued qualified unit facts changed.','stale_unit',412)
        item=native[('Item',line['item_code'])]
        if for_new and item.stock_uom!=unit['target']['name']:
            _fail('The current Item stock UOM must exactly equal the issued qualified UOM.')
        q=Decimal(line['quantity']);precision=unit['fields']['precision']
        if for_new and q!=q.quantize(Decimal(1).scaleb(-precision)):
            _fail('The issued quantity exceeds the qualified precision.','unsupported_native_precision')
        if for_new and frappe.db.exists('Product Bundle',{'new_item_code':line['item_code'],'disabled':0}):
            _fail('Product Bundle behavior is outside this bounded award adapter.')
    return {'company_version':version_of(company_doc),'base_currency':currency,'currency_policy':policy,
        'qualified_units':[qualified[name] for name in sorted(qualified)],
        'native_references':[{'doctype':kind,'name':name,'version':version_of(doc)} for (kind,name),doc in sorted(native.items())],
        'native_create_policy':['Project','Sales Order'],'payment_schedule_policy':PAYMENT_POLICY}


def _text(value):
    return '' if value is None else str(value)


def snapshot(*, sales_order_id, lock=False):
    """Current native-only integrity read; never locks Company/Project/masters.

    Financial values come from persisted SQL DECIMAL strings. The derived digest
    and final modified version stay outside the nonrecursive projection.
    """
    doc=frappe.get_doc('Sales Order',sales_order_id,for_update=lock)
    suffix=' FOR UPDATE' if lock else ''
    totals=frappe.db.sql('SELECT '+','.join('CAST(`'+field+'` AS CHAR) AS `'+field+'`' for field in HEADER_NUMBERS)+
        ' FROM `tabSales Order` WHERE name=%s'+suffix,(sales_order_id,),as_dict=True)
    if len(totals)!=1:_fail('The saved Sales Order header is unavailable.','native_award_integrity',409)
    rows=frappe.db.sql('SELECT '+','.join('`'+field+'`' for field in ROW_TEXT)+','+
        ','.join('CAST(`'+field+'` AS CHAR) AS `'+field+'`' for field in ROW_NUMBERS)+
        ' FROM `tabSales Order Item` WHERE parent=%s AND parenttype=%s ORDER BY cipher_award_line_id'+suffix,
        (sales_order_id,'Sales Order'),as_dict=True)
    if any(type(value) is not str for value in totals[0].values()) or any(type(row.get(field)) is not str for row in rows for field in ROW_NUMBERS):
        _fail('The persisted numeric projection is incomplete.','native_award_integrity',409)
    header={field:_text(doc.get(field)) for field in HEADER_TEXT}
    header.update(dict(totals[0]));header['docstatus']=int(doc.docstatus)
    projected=[];seen=set()
    for row in rows:
        identity=row.get('cipher_award_line_id')
        if not identity or identity in seen:_fail('Native award line identity is missing or duplicated.','native_award_integrity',409)
        seen.add(identity)
        projected.append({**{field:_text(row.get(field)) for field in ROW_TEXT},**{field:row[field] for field in ROW_NUMBERS}})
    payments=frappe.db.sql('SELECT '+','.join('`'+field+'`' for field in PAYMENT_TEXT)+','+
        ','.join('CAST(`'+field+'` AS CHAR) AS `'+field+'`' for field in PAYMENT_NUMBERS)+
        ' FROM `tabPayment Schedule` WHERE parent=%s AND parenttype=%s AND parentfield=%s ORDER BY idx'+suffix,
        (sales_order_id,'Sales Order','payment_schedule'),as_dict=True)
    if any(type(row.get(field)) is not str for row in payments for field in PAYMENT_NUMBERS):
        _fail('The persisted payment schedule decimals are incomplete.','native_award_integrity',409)
    payments=[{**{field:_text(row.get(field)) for field in PAYMENT_TEXT},
        **{field:row[field] for field in PAYMENT_NUMBERS}} for row in payments]
    projection={'schema':POLICY,'header':header,'rows':sorted(projected,key=lambda row:row['cipher_award_line_id']),
        'payment_schedule':payments}
    support={'tax_rows':len(doc.get('taxes') or []),'terms':doc.get('terms') or '', 'tc_name':doc.get('tc_name') or '',
        'taxes_and_charges':doc.get('taxes_and_charges') or '', 'shipping_rule':doc.get('shipping_rule') or '',
        'tax_category':doc.get('tax_category') or '', 'order_type':doc.get('order_type'),'status':doc.get('status'),
        'skip_delivery_note':int(doc.get('skip_delivery_note') or 0),'disable_rounded_total':int(doc.get('disable_rounded_total') or 0),
        'ignore_pricing_rule':int(doc.get('ignore_pricing_rule') or 0),
        'packed_item_count':len(doc.get('packed_items') or []),
        'unsupported_item_behavior':any(row.get('delivered_by_supplier') or row.get('warehouse') or row.get('is_stock_item') for row in doc.items)}
    return {'projection':projection,'digest':digest(projection),'version':version_of(doc),
        'derived_digest':doc.get('cipher_award_native_digest') or '', 'support':support}


def reconcile(actual, *, company, project, award_id, issue, lines, definition):
    from frappe.utils import escape_html
    projection=actual['projection'];header=projection['header'];rows=projection['rows']
    if projection.get('schema')!=POLICY or actual.get('digest')!=digest(projection):
        _fail('The persisted reconciliation projection digest cannot be verified.','native_award_integrity',409)
    expected={'company':company,'project':project,'customer':definition['customer'],'docstatus':0,
        'transaction_date':definition['transaction_date'],'delivery_date':definition['delivery_date'],
        'currency':issue['composition']['currency'],'selling_price_list':definition['selling_price_list'],
        'price_list_currency':issue['composition']['currency'],'apply_discount_on':'Grand Total','payment_terms_template':'',
        'cipher_award_handoff':award_id,'cipher_issue':issue['id'],'cipher_issue_digest':digest(issue),
        'cipher_proposal_revision':issue['proposal_revision'],'cipher_accepted_baseline':issue['accepted_estimate']['acceptance_id']}
    if any(header.get(key)!=value for key,value in expected.items()) or len(rows)!=len(lines):
        _fail('The saved native order does not preserve the exact reviewed award header/line set.')
    support=actual['support']
    if (support['tax_rows'] or support['packed_item_count'] or any(support[key] for key in ('taxes_and_charges','shipping_rule','tax_category','skip_delivery_note','unsupported_item_behavior','tc_name'))
            or support['order_type']!='Sales' or support['status']!='Draft' or not support['disable_rounded_total'] or not support['ignore_pricing_rule']
            or support['terms']!=escape_html(issue['composition']['terms']).replace('\n','<br>')):
        _fail('Native defaults introduced unsupported tax, stock, terms or order behavior.')
    by_id={row['cipher_award_line_id']:row for row in rows}
    if len(by_id)!=len(lines):_fail('Native stable line identities are ambiguous.')
    for line in lines:
        row=by_id.get(line['award_line_id']);uom=line['unit']['target']['name']
        expected_row={'cipher_proposal_line_id':line['proposal_line_id'],'item_code':line['item_code'],
            'description':escape_html(line['description']),'uom':uom,'stock_uom':uom,'delivery_date':line['delivery_date'],
            'prevdoc_docname':'','quotation_item':''}
        if row is None or any(row.get(key)!=value for key,value in expected_row.items()):
            _fail('Native controller output differs from the exact selected Issue line.')
        numeric={'qty':line['quantity'],'rate':line['rate'],'base_rate':line['rate'],'amount':line['amount'],
            'base_amount':line['amount'],'conversion_factor':'1','discount_percentage':'0','discount_amount':'0'}
        if any(Decimal(row[key])!=Decimal(value) for key,value in numeric.items()):
            _fail('Native persisted decimals cannot exactly represent the issued selling facts.','unsupported_native_precision')
    numeric={key:issue['pricing']['total'] for key in ('total','net_total','grand_total','base_total','base_net_total','base_grand_total')}
    numeric.update({key:'0' for key in ('rounded_total','base_rounded_total','total_taxes_and_charges','discount_amount','additional_discount_percentage')})
    numeric.update(conversion_rate='1',plc_conversion_rate='1')
    if any(Decimal(header[key])!=Decimal(value) for key,value in numeric.items()):
        _fail('Saved native totals cannot exactly represent the issued total without FX, tax, discount or rounding.','unsupported_native_precision')
    payments=projection.get('payment_schedule')
    if type(payments) is not list or len(payments)!=1:
        _fail('The native draft requires one reviewed default payment schedule row.')
    payment=payments[0]
    if (set(payment)!=set(PAYMENT_TEXT)|set(PAYMENT_NUMBERS) or not payment['name']
            or payment['due_date']!=definition['transaction_date'] or payment['discount_type']!='Percentage'
            or any(payment[field] for field in ('payment_term','description','mode_of_payment','discount_date',
                'due_date_based_on','discount_validity_based_on'))):
        _fail('Native defaults introduced unreviewed payment terms or dates.')
    expected_payment={field:'0' for field in PAYMENT_NUMBERS}
    expected_payment.update(invoice_portion='100',payment_amount=issue['pricing']['total'],
        base_payment_amount=issue['pricing']['total'],outstanding=issue['pricing']['total'],base_outstanding=issue['pricing']['total'])
    if any(Decimal(payment[field])!=Decimal(value) for field,value in expected_payment.items()):
        _fail('The saved native draft payment schedule changed reviewed amounts or discounts.','unsupported_native_precision')
    return actual['digest']


def create_order(*, actor, company, project, award_id, award_revision_id, plan_digest, issue, lines, definition,
                 packet_id, decision_id, operation_id, resource_token):
    from .effect import require_award_effect, native_order_effect
    from frappe.utils import escape_html
    context=dict(company=company,project=project,award_id=award_id,award_revision_id=award_revision_id,
        plan_digest=plan_digest,packet_id=packet_id,decision_id=decision_id,operation_id=operation_id)
    require_award_effect(**context)
    plan_resources(company=company,issue=issue,lines=lines,definition=definition,actor=actor,lock=True)
    authorize_sources(actor=actor,company=company,lines=lines,definition=definition,resource_token=resource_token,
        lock=True,for_new=True,require_create=True)
    project_doc=frappe.get_doc('Project',project,for_update=True)
    if project_doc.company!=company or project_doc.customer!=definition['customer']:
        _fail('The exact newly created Project must preserve the award Company and Customer.')
    if any(not frappe.get_meta('Sales Order').has_field(field) for field in SOURCE_LINKS) or any(
            not frappe.get_meta('Sales Order Item').has_field(field) for field in ('cipher_award_line_id','cipher_proposal_line_id')):
        _fail('Install the supported native award lineage fields before creating an order.','native_award_setup_required',503)
    currency=issue['composition']['currency']
    order=frappe.get_doc({'doctype':'Sales Order','company':company,'project':project,'customer':definition['customer'],
        'order_type':'Sales','transaction_date':definition['transaction_date'],'delivery_date':definition['delivery_date'],
        'currency':currency,'conversion_rate':1,'selling_price_list':definition['selling_price_list'],
        'price_list_currency':currency,'plc_conversion_rate':1,'ignore_pricing_rule':1,'disable_rounded_total':1,
        'apply_discount_on':'Grand Total','additional_discount_percentage':0,'discount_amount':0,
        'taxes_and_charges':'','tax_category':'','shipping_rule':'','taxes':[],
        'payment_terms_template':'','tc_name':'','terms':escape_html(issue['composition']['terms']).replace('\n','<br>'),
        'cipher_award_handoff':award_id,'cipher_issue':issue['id'],'cipher_issue_digest':digest(issue),
        'cipher_proposal_revision':issue['proposal_revision'],'cipher_accepted_baseline':issue['accepted_estimate']['acceptance_id']})
    order.flags.notify_update=False
    if order.get('payment_terms_template'):
        _fail('An award order cannot inherit a native payment terms template.','native_award_integrity',409)
    if order.get('tc_name'):
        _fail('An award order cannot copy native Terms and Conditions attachments.','native_award_integrity',409)
    if order.get('amended_from') or order.flags.get('updater_reference') or order.get('_doc_before_save'):
        _fail('A fresh award order cannot introduce amendment or native Version lineage.','native_award_integrity',409)
    for line in lines:
        uom=line['unit']['target']['name']
        order.append('items',{'cipher_award_line_id':line['award_line_id'],'cipher_proposal_line_id':line['proposal_line_id'],
            'item_code':line['item_code'],'description':escape_html(line['description']),'qty':line['quantity'],
            'rate':line['rate'],'base_rate':line['rate'],'amount':line['amount'],'base_amount':line['amount'],
            'price_list_rate':line['rate'],'uom':uom,'stock_uom':uom,'conversion_factor':1,
            'delivery_date':line['delivery_date'],'discount_percentage':0,'discount_amount':0,
            'prevdoc_docname':'','quotation_item':'','delivered_by_supplier':0})
    with native_order_effect(**context,issue=issue,lines=lines,definition=definition,actor=actor):
        try:
            order.insert(ignore_permissions=True)
            first=snapshot(sales_order_id=order.name,lock=True)
            value=reconcile(first,company=company,project=project,award_id=award_id,issue=issue,lines=lines,definition=definition)
            order.cipher_award_native_digest=value
            # This supported second save adds only the derived reconciliation
            # digest. Cipher preserves both exact snapshots; do not create a
            # transitive native Version with its own configurable callbacks.
            missing_version_flag=object()
            previous_version_flag=order.flags.get('ignore_version',missing_version_flag)
            order.flags.ignore_version=True
            try:
                order.save(ignore_permissions=True,ignore_version=True)
            finally:
                if previous_version_flag is missing_version_flag:
                    order.flags.pop('ignore_version',None)
                else:
                    order.flags.ignore_version=previous_version_flag
            final=snapshot(sales_order_id=order.name,lock=True)
            reconcile(final,company=company,project=project,award_id=award_id,issue=issue,lines=lines,definition=definition)
            if final['projection']!=first['projection'] or final['derived_digest']!=value:
                _fail('The second supported save changed the reconciled native projection.')
        except (frappe.PermissionError,frappe.ValidationError) as error:
            if isinstance(error,DomainError):raise
            raise DomainError('native_award_validation','ERPNext could not validate this exact draft order against the current native setup.',422) from error
    return {'sales_order':order.name,'native_snapshot':final,'native_digest':value,'native_version':final['version']}
