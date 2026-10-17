"""Draft adapter source/resource and persisted-projection invariants, without writes."""
import copy
from contextlib import ExitStack
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from uuid import NAMESPACE_URL, uuid5

from frappe import _dict

from cipher_aec.api.contracts import digest
from cipher_aec.api.errors import DomainError
from cipher_aec.awards import native


def identity(label):return str(uuid5(NAMESPACE_URL,'cipher-award-test:'+label))

def record(**fields):
    value=SimpleNamespace(**fields);value.get=lambda key,default=None:getattr(value,key,default);return value


def fixtures():
    unit={'id':identity('unit'),'kind':'uom','revision':1,'fields':{'symbol':'EA','dimension':'count','precision':0},'target':{'doctype':'UOM','name':'Count'}}
    line={'award_line_id':identity('adoption'),'proposal_line_id':identity('proposal-line'),'description':'Worked <scope>',
        'item_code':'Existing service','quantity':'2','rate':'15.00','amount':'30.00','unit':unit,'currency':'USD',
        'conversion_factor':{'numerator':'1','denominator':'1'},'delivery_date':'2026-10-22'}
    source={'id':line['proposal_line_id'],'selected':True,'item_code':None,'description':line['description'],
        'unit_id':unit['id'],'unit_revision':1,'quantity':'2','rate':'15.00','amount':'30.00'}
    issue={'id':identity('issue'),'company':'Company A','status':'issued','native_lifecycle':'draft-snapshot',
        'proposal_revision':identity('revision'),'accepted_estimate':{'acceptance_id':identity('baseline')},
        'composition':{'currency':'USD','terms':'Original terms'},'pricing':{'total':'30.00'},'selected_lines':[{'line':source,'unit':unit}]}
    definition={'customer':'Existing customer','transaction_date':'2026-10-20','delivery_date':'2026-10-22','selling_price_list':'Existing USD selling'}
    return issue,[line],definition


class AwardNative(TestCase):
    def setUp(self):
        self.canonical_patch=patch.object(native,'_canonical_names');self.canonical_patch.start();self.addCleanup(self.canonical_patch.stop)
        self.issue,self.lines,self.definition=fixtures();self.actor=record(user='author@example.test',person_id=identity('person'))
        self.required=native.plan_resources(company='Company A',issue=self.issue,lines=self.lines,definition=self.definition,actor=self.actor)

    def actual(self):
        from frappe.utils import escape_html
        line=self.lines[0]
        header={key:'' for key in native.HEADER_TEXT}
        header.update(name='SO-test',company='Company A',project='Project A',customer=self.definition['customer'],docstatus=0,
            transaction_date=self.definition['transaction_date'],delivery_date=self.definition['delivery_date'],currency='USD',
            selling_price_list=self.definition['selling_price_list'],price_list_currency='USD',apply_discount_on='Grand Total',
            cipher_award_handoff=identity('award'),cipher_issue=self.issue['id'],cipher_issue_digest=digest(self.issue),
            cipher_proposal_revision=self.issue['proposal_revision'],cipher_accepted_baseline=self.issue['accepted_estimate']['acceptance_id'])
        header.update({key:'0.000000000' for key in native.HEADER_NUMBERS})
        header.update({key:'30.000000000' for key in ('total','net_total','grand_total','base_total','base_net_total','base_grand_total')})
        header.update(conversion_rate='1.000000000',plc_conversion_rate='1.000000000')
        row={key:'' for key in native.ROW_TEXT}
        row.update(name='SOI-test',cipher_award_line_id=line['award_line_id'],cipher_proposal_line_id=line['proposal_line_id'],
            item_code=line['item_code'],description=escape_html(line['description']),uom='Count',stock_uom='Count',delivery_date=line['delivery_date'])
        row.update(qty='2.000000000',rate='15.000000000',amount='30.000000000',base_rate='15.000000000',base_amount='30.000000000',
            conversion_factor='1.000000000',discount_percentage='0.000000000',discount_amount='0.000000000')
        payment={key:'' for key in native.PAYMENT_TEXT}
        payment.update(name='PAY-test',due_date=self.definition['transaction_date'],discount_type='Percentage')
        payment.update({key:'0.000000000' for key in native.PAYMENT_NUMBERS})
        payment.update(invoice_portion='100.000000000',payment_amount='30.000000000',base_payment_amount='30.000000000',
            outstanding='30.000000000',base_outstanding='30.000000000')
        projection={'schema':native.POLICY,'header':header,'rows':[row],'payment_schedule':[payment]}
        return {'projection':projection,'digest':digest(projection),'version':'version1','derived_digest':'',
            'support':{'tc_name':'','tax_rows':0,'packed_item_count':0,'terms':'Original terms','taxes_and_charges':'','shipping_rule':'','tax_category':'',
                'order_type':'Sales','status':'Draft','skip_delivery_note':0,'disable_rounded_total':1,'ignore_pricing_rule':1,'unsupported_item_behavior':False}}

    def reconcile(self,value):
        return native.reconcile(value,company='Company A',project='Project A',award_id=identity('award'),issue=self.issue,lines=self.lines,definition=self.definition)

    def test_discovery_preserves_exact_issued_selection_and_explicit_freeform_mapping(self):
        self.assertEqual(self.required['unit_ids'],[self.lines[0]['unit']['id']])
        self.assertIn({'doctype':'Item','name':'Existing service'},self.required['native_refs'])
        self.assertEqual(self.required['generated_sources'],[])
        for field,value in (('rate','15.01'),('amount','30.01'),('description','Changed'),('quantity','3')):
            old=self.lines[0][field];self.lines[0][field]=value
            try:
                with self.subTest(field=field),self.assertRaises(DomainError):native.plan_resources(company='Company A',issue=self.issue,lines=self.lines,definition=self.definition,actor=self.actor)
            finally:self.lines[0][field]=old
        self.issue['selected_lines'][0]['line']['item_code']='Original Item'
        with self.assertRaises(DomainError):native.plan_resources(company='Company A',issue=self.issue,lines=self.lines,definition=self.definition,actor=self.actor)

    def sources(self):
        stack=ExitStack()
        self.company=record(name='Company A',default_currency='USD',modified='company-v1')
        self.item=record(name='Existing service',stock_uom='Count',disabled=0,is_sales_item=1,is_stock_item=0,modified='item-v1')
        self.customer=record(name='Existing customer',disabled=0,is_internal_customer=0,modified='customer-v1')
        self.price=record(name='Existing USD selling',enabled=1,selling=1,currency='USD',modified='price-v1')
        self.reader=record(fetch=lambda kind,name,lock=False:self.item if kind=='item' else self.customer)
        stack.enter_context(patch.object(native,'is_prelocked',return_value=True))
        stack.enter_context(patch.object(native,'require_company',return_value=self.company))
        creates=stack.enter_context(patch.object(native.commercial,'can_create'))
        stack.enter_context(patch.object(native.commercial,'require_native',return_value=self.price))
        stack.enter_context(patch.object(native.units,'qualified',return_value=copy.deepcopy(self.lines[0]['unit'])))
        stack.enter_context(patch.object(native.units,'currency_policy',return_value={'currency':'USD','currency_exponent':2}))
        stack.enter_context(patch('cipher_aec.migrations.export.FrappeCompanyTargetReader',return_value=self.reader))
        stack.enter_context(patch.object(native,'frappe',record(db=record(exists=lambda *a,**k:False))))
        return stack,creates

    def authorize(self,token=None):
        return native.authorize_sources(actor=self.actor,company='Company A',lines=self.lines,definition=self.definition,
            resource_token=self.required if token is None else token,lock=True)

    def test_missing_resources_refuse_before_any_master_or_company_acquisition(self):
        with patch.object(native,'is_prelocked',return_value=True),patch.object(native,'require_company',side_effect=AssertionError('Late authorization')):
            with self.assertRaises(DomainError) as error:self.authorize({})
            self.assertEqual(error.exception.code,'source_prelock_required')
        with patch.object(native,'is_prelocked',return_value=False):
            with self.assertRaises(DomainError):self.authorize()

    def test_current_native_create_permissions_and_sources_are_separate_from_company_authority(self):
        stack,creates=self.sources()
        with stack:
            actual=self.authorize();self.assertEqual(actual['native_create_policy'],['Project','Sales Order'])
            self.assertEqual([call.args[0] for call in creates.call_args_list],['Project','Sales Order'])
            creates.side_effect=DomainError('native_permission_denied','Denied',403)
            with self.assertRaises(DomainError):self.authorize()

    def test_unsupported_item_unit_currency_and_native_defaults_fail_closed(self):
        stack,creates=self.sources()
        with stack:
            for doc,field,value in ((self.item,'disabled',1),(self.item,'is_sales_item',0),(self.item,'is_stock_item',1),
                (self.item,'stock_uom','Other UOM'),(self.company,'default_currency','EUR'),(self.price,'currency','EUR'),(self.price,'enabled',0)):
                old=getattr(doc,field);setattr(doc,field,value)
                try:
                    with self.subTest(field=field,value=value),self.assertRaises(DomainError):self.authorize()
                finally:setattr(doc,field,old)
            self.reader.fetch=lambda *a,**k:None
            with self.assertRaises(DomainError):self.authorize()

    def test_sql_decimal_reconciliation_refuses_precision_rounding_source_and_identity_changes(self):
        actual=self.actual();self.assertEqual(self.reconcile(actual),actual['digest'])
        for section,field,value in (('header','grand_total','30.000000001'),('header','conversion_rate','1.01'),
            ('header','rounded_total','30.00'),('header','cipher_issue','different'),('row','qty','2.000000001'),
            ('row','amount','30.01'),('row','uom','Other'),('row','prevdoc_docname','Quotation'),('row','cipher_award_line_id',identity('other'))):
            changed=copy.deepcopy(actual);target=changed['projection']['rows'][0] if section=='row' else changed['projection']['header'];target[field]=value
            changed['digest']=digest(changed['projection'])
            with self.subTest(section=section,field=field),self.assertRaises(DomainError):self.reconcile(changed)
        for field,value in (('tax_rows',1),('packed_item_count',1),('unsupported_item_behavior',True),('terms','Changed'),('shipping_rule','Unreviewed')):
            changed=copy.deepcopy(actual);changed['support'][field]=value
            with self.subTest(field=field),self.assertRaises(DomainError):self.reconcile(changed)

    def test_snapshot_projection_excludes_derived_digest_modified_and_native_row_adjacency(self):
        expected=self.actual();head=expected['projection']['header'];row=expected['projection']['rows'][0]
        doc=record(**{**head,**expected['support'],'modified':'v1','cipher_award_native_digest':'old','taxes':[],'items':[record(**row)],'packed_items':[]})
        def sql(query,*a,**k):
            if 'FROM `tabSales Order Item`' in query:return [row]
            if 'FROM `tabPayment Schedule`' in query:return copy.deepcopy(expected['projection']['payment_schedule'])
            return [{key:head[key] for key in native.HEADER_NUMBERS}]
        fake=record(get_doc=lambda *a,**k:doc,db=record(sql=sql))
        with patch.object(native,'frappe',fake):
            one=native.snapshot(sales_order_id='SO-test',lock=True)
            doc.modified='v2';doc.cipher_award_native_digest=one['digest'];doc.items[0].idx=7
            two=native.snapshot(sales_order_id='SO-test',lock=True)
        self.assertEqual(one['projection'],two['projection']);self.assertEqual(one['digest'],two['digest'])
        self.assertNotEqual(one['version'],two['version']);self.assertEqual(two['derived_digest'],one['digest'])
        self.assertEqual(set(one['projection']['header']),set(native.HEADER_TEXT)|set(native.HEADER_NUMBERS)|{'docstatus'})
        self.assertEqual(set(one['projection']['rows'][0]),set(native.ROW_TEXT)|set(native.ROW_NUMBERS))

    def test_unrelated_call_cannot_allocate_any_native_order_without_exact_award_effect(self):
        with patch('cipher_aec.awards.effect.require_award_effect',side_effect=DomainError('award_effect_required','Denied',403)),patch.object(native,'frappe',record(get_doc=lambda *a,**k:(_ for _ in ()).throw(AssertionError('Unauthorized native allocation')))):
            with self.assertRaises(DomainError):native.create_order(actor=self.actor,company='Company A',project='Project A',award_id=identity('award'),
                award_revision_id=identity('award-revision'),plan_digest='a'*64,issue=self.issue,lines=self.lines,definition=self.definition,
                packet_id=identity('packet'),decision_id=identity('decision'),operation_id=identity('command'),resource_token=self.required)

    def test_independent_reviewer_rechecks_current_sources_without_claiming_create_rights(self):
        stack,creates=self.sources()
        with stack:
            creates.side_effect=AssertionError('Reviewer was asked for native create authority')
            value=native.authorize_sources(actor=self.actor,company='Company A',lines=self.lines,definition=self.definition,
                resource_token=self.required,lock=True,require_create=False)
            self.assertEqual(value['native_create_policy'],['Project','Sales Order'])
            self.item.disabled=1
            with self.assertRaises(DomainError):native.authorize_sources(actor=self.actor,company='Company A',lines=self.lines,
                definition=self.definition,resource_token=self.required,lock=True,require_create=False)

    def test_historical_read_allows_disabled_sources_without_new_use_policy_or_create_grant(self):
        stack,creates=self.sources()
        with stack,patch.object(native.units,'currency_policy',side_effect=AssertionError('Historical currency was repriced')):
            creates.side_effect=AssertionError('Historical read was asked for native create authority')
            self.item.disabled=1;self.item.is_stock_item=1;self.item.stock_uom='Changed later';self.customer.disabled=1
            self.price.enabled=0;self.price.currency='EUR';self.company.default_currency='EUR'
            result=native.authorize_sources(actor=self.actor,company='Company A',lines=self.lines,definition=self.definition,
                resource_token=self.required,lock=True,for_new=False,require_create=False)
            self.assertEqual(result['currency_policy']['currency'],'USD')
            self.assertNotIn('currency_exponent',result['currency_policy'])
            self.reader.fetch=lambda *a,**k:None
            with self.assertRaises(DomainError):native.authorize_sources(actor=self.actor,company='Company A',lines=self.lines,
                definition=self.definition,resource_token=self.required,lock=True,for_new=False,require_create=False)

    def test_factory_uses_two_supported_saves_and_checks_post_save_projection(self):
        from contextlib import contextmanager
        from cipher_aec.awards import effect
        for drift in (False,True):
            events=[];first=self.actual();final=copy.deepcopy(first);final['version']='v2';final['derived_digest']=first['digest']
            if drift:
                final['projection']['rows'][0]['name']='Different persisted child name'
                final['digest']=digest(final['projection'])
            order=record(name='SO-test',flags=_dict(),append=lambda *a,**k:None,
                insert=lambda **k:events.append('insert'),save=lambda **k:events.append('save'))
            def get_doc(doctype,*a,**k):
                if type(doctype) is dict:
                    self.assertEqual(doctype['tc_name'],'');return order
                self.assertEqual(doctype,'Project');return record(company='Company A',customer=self.definition['customer'])
            @contextmanager
            def native_context(**kwargs):
                events.append('enter');yield;events.append('exit')
            fake=record(get_doc=get_doc,get_meta=lambda dt:record(has_field=lambda field:True),
                PermissionError=PermissionError,ValidationError=ValueError)
            with (patch.object(native,'frappe',fake),patch.object(native,'plan_resources',return_value=self.required),
                patch.object(native,'authorize_sources') as authorized,patch.object(native,'snapshot',side_effect=[first,final]) as stored,
                patch.object(effect,'require_award_effect') as required,patch.object(effect,'native_order_effect',native_context)):
                def create():return native.create_order(actor=self.actor,company='Company A',project='Project A',award_id=identity('award'),
                    award_revision_id=identity('award-revision'),plan_digest='a'*64,issue=self.issue,lines=self.lines,definition=self.definition,
                    packet_id=identity('packet'),decision_id=identity('decision'),operation_id=identity('command'),resource_token=self.required)
                if drift:
                    with self.assertRaises(DomainError):create()
                else:
                    result=create();self.assertEqual(result['native_version'],'v2');self.assertEqual(result['native_digest'],first['digest'])
                    self.assertEqual(events,['enter','insert','save','exit'])
                self.assertFalse(order.flags.notify_update)
                self.assertEqual(stored.call_count,2);self.assertEqual(order.cipher_award_native_digest,first['digest'])
                self.assertTrue(authorized.call_args.kwargs['for_new']);self.assertTrue(authorized.call_args.kwargs['require_create'])

    def test_required_runtime_profile_failure_prevents_first_supported_insert(self):
        from cipher_aec.awards import effect
        events=[]
        order=record(name=None,flags=record(),append=lambda *a,**k:None,
            insert=lambda **k:events.append('insert'),save=lambda **k:events.append('save'))
        def get_doc(doctype,*a,**k):
            return order if type(doctype) is dict else record(company='Company A',customer=self.definition['customer'])
        fake=record(get_doc=get_doc,get_meta=lambda dt:record(has_field=lambda field:True))
        with (patch.object(native,'frappe',fake),patch.object(native,'plan_resources',return_value=self.required),
            patch.object(native,'authorize_sources'),patch.object(effect,'require_award_effect',return_value={
                'issue_digest':digest(self.issue),'lines_digest':digest(self.lines),'native_definition_digest':digest(self.definition)}),
            patch('cipher_aec.awards.runtime.require_native_profile',side_effect=DomainError('native_profile_required','Profile is unavailable',503)) as profile):
            with self.assertRaises(DomainError) as error:native.create_order(actor=self.actor,company='Company A',project='Project A',award_id=identity('award'),
                award_revision_id=identity('award-revision'),plan_digest='a'*64,issue=self.issue,lines=self.lines,definition=self.definition,
                packet_id=identity('packet'),decision_id=identity('decision'),operation_id=identity('command'),resource_token=self.required)
            self.assertEqual(error.exception.code,'native_profile_required');profile.assert_called_once_with()
        self.assertEqual(events,[]);self.assertFalse(order.flags.notify_update)

    def test_ignore_version_is_scoped_to_derived_save_and_restored_even_on_failure(self):
        from contextlib import contextmanager
        from cipher_aec.awards import effect
        absent=object()
        for previous in (absent,False,True):
            for fails in (False,True):
                with self.subTest(previous='absent' if previous is absent else previous,fails=fails):
                    events=[];first=self.actual();final=copy.deepcopy(first)
                    final['version']='v2';final['derived_digest']=first['digest']
                    flags=_dict()
                    if previous is not absent:flags.ignore_version=previous
                    def insert(**kwargs):
                        events.append('insert')
                        self.assertIs(flags.get('ignore_version',absent),previous)
                        self.assertFalse(flags.notify_update)
                    def save(**kwargs):
                        events.append('save')
                        # Pinned Document._save overwrites the flag from this
                        # supported keyword (frappe.in_test defaults False).
                        flags.ignore_version=kwargs.get('ignore_version',False)
                        self.assertIs(kwargs.get('ignore_version'),True)
                        self.assertIs(flags.ignore_version,True)
                        self.assertFalse(flags.notify_update)
                        if fails:raise ValueError('supported native save failed')
                    order=record(name='SO-test',flags=flags,append=lambda *a,**k:None,insert=insert,save=save)
                    def get_doc(doctype,*args,**kwargs):
                        return order if type(doctype) is dict else record(company='Company A',customer=self.definition['customer'])
                    @contextmanager
                    def native_context(**kwargs):yield
                    fake=record(get_doc=get_doc,get_meta=lambda dt:record(has_field=lambda field:True),
                        PermissionError=PermissionError,ValidationError=ValueError)
                    with (patch.object(native,'frappe',fake),patch.object(native,'plan_resources',return_value=self.required),
                        patch.object(native,'authorize_sources'),patch.object(native,'snapshot',side_effect=[first,final]),
                        patch.object(effect,'require_award_effect'),patch.object(effect,'native_order_effect',native_context)):
                        def create():return native.create_order(actor=self.actor,company='Company A',project='Project A',award_id=identity('award'),
                            award_revision_id=identity('award-revision'),plan_digest='a'*64,issue=self.issue,lines=self.lines,definition=self.definition,
                            packet_id=identity('packet'),decision_id=identity('decision'),operation_id=identity('command'),resource_token=self.required)
                        if fails:
                            with self.assertRaises(DomainError) as error:create()
                            self.assertEqual(error.exception.code,'native_award_validation')
                        else:create()
                    self.assertEqual(events,['insert','save'])
                    self.assertIs(flags.get('ignore_version',absent),previous)

    def test_pinned_first_insert_has_no_version_insert_even_when_tracking_enabled(self):
        from frappe.model import document
        for doctype in ('Project','Sales Order'):
            for track_changes in (False,True):
                doc=record(doctype=doctype,meta=record(track_changes=track_changes),flags=_dict(),
                    _doc_before_save=None,get=lambda field:None)
                version=record(insert=lambda **kwargs:self.fail('A first insert must not persist Version'),
                    update_version_info=lambda *args:self.fail('There is no predecessor to compare'))
                fake=record(flags=_dict(),new_doc=lambda name:version)
                with patch.object(document,'frappe',fake):
                    with self.subTest(doctype=doctype,track_changes=track_changes):document.Document.save_version(doc)

    def test_supported_ignore_version_exits_before_constructing_transitive_document(self):
        from frappe.model import document
        doc=record(doctype='Sales Order',meta=record(track_changes=True),flags=_dict(ignore_version=True),
            _doc_before_save=object(),get=lambda field:None)
        fake=record(flags=_dict(),new_doc=lambda name:self.fail('Version construction must be skipped'))
        with patch.object(document,'frappe',fake):document.Document.save_version(doc)

    def test_first_insert_refuses_amendment_updater_or_prior_document_before_write(self):
        from cipher_aec.awards import effect
        for field in ('amended_from','updater_reference','_doc_before_save','tc_name','payment_terms_template'):
            flags=_dict();events=[]
            order=record(name=None,flags=flags,append=lambda *a,**k:None,
                insert=lambda **k:events.append('insert'),save=lambda **k:events.append('save'))
            if field=='updater_reference':flags.updater_reference='unexpected'
            else:setattr(order,field,'unexpected')
            def get_doc(doctype,*args,**kwargs):
                return order if type(doctype) is dict else record(company='Company A',customer=self.definition['customer'])
            fake=record(get_doc=get_doc,get_meta=lambda dt:record(has_field=lambda field:True))
            with (patch.object(native,'frappe',fake),patch.object(native,'plan_resources',return_value=self.required),
                patch.object(native,'authorize_sources'),patch.object(effect,'require_award_effect'),
                patch.object(effect,'native_order_effect') as writer):
                with self.subTest(field=field),self.assertRaises(DomainError) as error:
                    native.create_order(actor=self.actor,company='Company A',project='Project A',award_id=identity('award'),
                        award_revision_id=identity('award-revision'),plan_digest='a'*64,issue=self.issue,lines=self.lines,definition=self.definition,
                        packet_id=identity('packet'),decision_id=identity('decision'),operation_id=identity('command'),resource_token=self.required)
                self.assertEqual(error.exception.code,'native_award_integrity');writer.assert_not_called()
            self.assertEqual(events,[])

    def test_reconciliation_refuses_default_populated_terms_template(self):
        value=self.actual();value['support']['tc_name']='Default Terms with copyable attachments'
        with self.assertRaises(DomainError):self.reconcile(value)

    def test_payment_schedule_policy_is_static_and_rejects_unreviewed_native_defaults(self):
        actual=self.actual();self.reconcile(actual)
        for field,value in (('payment_term','Net30'),('description','Unreviewed'),('due_date','2026-11-20'),
            ('mode_of_payment','Bank'),('discount','1'),('payment_amount','29.99'),('outstanding','0'),
            ('credit_days','30'),('invoice_portion','50')):
            changed=copy.deepcopy(actual);changed['projection']['payment_schedule'][0][field]=value
            changed['digest']=digest(changed['projection'])
            with self.subTest(field=field),self.assertRaises(DomainError):self.reconcile(changed)
        for payments in ([],actual['projection']['payment_schedule']*2):
            changed=copy.deepcopy(actual);changed['projection']['payment_schedule']=payments;changed['digest']=digest(changed['projection'])
            with self.assertRaises(DomainError):self.reconcile(changed)
        changed=copy.deepcopy(actual);changed['projection']['header']['payment_terms_template']='Inherited'
        changed['digest']=digest(changed['projection'])
        with self.assertRaises(DomainError):self.reconcile(changed)
        stack,_=self.sources()
        with stack:self.assertEqual(self.authorize()['payment_schedule_policy'],native.PAYMENT_POLICY)

    def test_case_accent_aliases_fail_metadata_discovery_before_any_lock_union(self):
        self.canonical_patch.stop()
        for field,value,stored in (('customer','existing customer','Existing customer'),
            ('customer','Éxisting customer','Existing customer'),('selling_price_list','existing usd selling','Existing USD selling'),
            ('item_code','existing service','Existing service')):
            issue,lines,definition=fixtures()
            if field=='item_code':lines[0][field]=value
            else:definition[field]=value
            calls=[]
            def get_value(kind,name,column,**kwargs):
                calls.append((kind,name,column,kwargs));self.assertEqual(kwargs,{'cache':False})
                return stored if name==value else name
            with patch.object(native,'frappe',record(db=record(get_value=get_value))),patch.object(native,'_required',side_effect=AssertionError('Aliased lock union')):
                with self.subTest(field=field,value=value),self.assertRaises(DomainError) as error:
                    native.plan_resources(company='Company A',issue=issue,lines=lines,definition=definition,actor=self.actor)
                self.assertEqual(error.exception.code,'not_found');self.assertTrue(calls)

    def test_locked_native_source_must_retain_exact_reviewed_name(self):
        for field in ('customer','item','price'):
            stack,_=self.sources()
            with stack:
                obj=getattr(self,field);obj.name=obj.name.lower()
                with self.subTest(field=field),self.assertRaises(DomainError) as error:self.authorize()
                self.assertEqual(error.exception.code,'not_found')

    def test_pinned_save_entry_overwrites_flag_unless_explicit_keyword_is_passed(self):
        from frappe.model import document
        class StopBeforeAnyDatabaseWork(Exception):pass
        for supplied,expected in ((None,False),(True,True)):
            doc=record(name='Existing',flags=_dict(ignore_version=True),
                check_if_locked=lambda:(_ for _ in ()).throw(StopBeforeAnyDatabaseWork()))
            with patch.object(document,'frappe',record(in_test=False)):
                with self.assertRaises(StopBeforeAnyDatabaseWork):
                    document.Document._save(doc,ignore_permissions=True,ignore_version=supplied)
            self.assertIs(doc.flags.ignore_version,expected)
