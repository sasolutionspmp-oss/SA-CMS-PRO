"""Finite native target selectors authorize every row before SQL-keyset paging."""
from contextlib import ExitStack
import json
import sqlite3
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
from uuid import uuid4
from cipher_aec.api import masters
from cipher_aec.api.errors import DomainError


def doc(**fields):
    value=SimpleNamespace(**fields);value.get=lambda k,default=None:getattr(value,k,default);return value


class AwardSelectorTests(unittest.TestCase):
    def setUp(self):
        self.sql=sqlite3.connect(':memory:');self.sql.row_factory=sqlite3.Row;self.addCleanup(self.sql.close)
        for kind in ('Cost Center','Account','Item'):
            self.sql.execute('CREATE TABLE `tab'+kind+'` (name TEXT COLLATE NOCASE)')
        self.rows={};self.hidden=set();self.corrupt=set();self.actor=doc(user='author',person_id='person');self.unit=str(uuid4());self.calls=[]
        def query(q,args,**kw):
            if 'tabUser Permission' in q:return []
            return [doc(**dict(r)) for r in self.sql.execute(q.replace('%s','?'),args)]
        def native(kind,name,actor):
            self.calls.append((kind,name))
            if name in self.hidden:raise DomainError('not_found','Hidden',404)
            if name in self.corrupt:raise DomainError('source_integrity','Invalid',409)
            if kind=='UOM':return doc(name=name,enabled=1,cipher_unit_id=self.unit)
            if kind=='Currency':return doc(name=name,enabled=1)
            return self.rows[name]
        self.authorize=Mock(return_value=doc(name='A',default_currency='USD'))
        stack=ExitStack();self.addCleanup(stack.close)
        for p in (patch.object(masters,'frappe',doc(db=doc(sql=query,get_value=lambda *a:'version',exists=lambda *a:False),get_roles=lambda *a:[],as_json=json.dumps)),
                patch.object(masters,'current_actor',return_value=self.actor),patch.object(masters,'require_company',self.authorize),
                patch.object(masters,'company_authority_fingerprint',return_value='current'),patch.object(masters,'require_native',side_effect=native),
                patch.object(masters,'signing_secret',return_value='test-key'),patch('cipher_aec.api.paging.signing_secret',return_value='test-key'),patch.object(masters,'qualified',return_value={'id':self.unit,'revision':1,'target':{'name':'Count'},'fields':{'dimension':'count','precision':0}}),
                patch.object(masters,'currency_policy',return_value={'currency_exponent':2}),patch.object(masters,'CHUNK',2)):
            stack.enter_context(p)
    def add(self,kind,name,**attrs):
        self.sql.execute('INSERT INTO `tab'+kind+'` VALUES(?)',(name,))
        self.rows[name]=doc(name=name,company='A',modified='native-version',is_group=0,disabled=0,root_type='Expense',account_currency='USD',
            item_name=name,stock_uom='Count',item_defaults=[doc(company='A')],is_sales_item=1,is_stock_item=0,has_variants=0,is_fixed_asset=0,is_sub_contracted_item=0,**attrs)
    def test_exact_scope_native_private_offpage_and_account_currency(self):
        self.add('Account','Expense A');self.add('Account','Expense B');self.rows['Expense B'].company='other'
        result=masters._choose('A','accounts',count_mode='exact')
        self.assertEqual(result['total'],1);self.assertEqual(result['items'][0]['currency'],'USD')
        self.assertEqual(self.authorize.call_args.kwargs['ability'],'project.cost.read')
        self.hidden={'Expense A'};result=masters._choose('A','accounts',count_mode='exact')
        self.assertEqual((result['items'],result['total'],result['next_cursor']),([],0,None))
    def test_native_sql_name_collation_controls_cursor_selection(self):
        self.add('Cost Center','a');self.add('Cost Center','B');self.add('Cost Center','c')
        first=masters._choose('A','cost_centers',limit=1,count_mode='exact')
        self.assertEqual(first['items'][0]['id'],'a');self.assertEqual(first['total'],3)
        next_page=masters._choose('A','cost_centers',limit=1,count_mode='exact',cursor=first['next_cursor'])
        self.assertEqual(next_page['items'][0]['id'],'B')
        with self.assertRaises(DomainError):masters._choose('A','cost_centers',query='different',cursor=first['next_cursor'])
    def test_award_items_are_existing_nonstock_sales_and_private_unit_filter_denies_empty_scope(self):
        self.add('Item','service');self.add('Item','stock');self.rows['stock'].is_stock_item=1
        result=masters._choose('A','award_items',count_mode='exact')
        self.assertEqual([r['id'] for r in result['items']],['service'])
        self.assertEqual(self.authorize.call_args.kwargs['ability'],'commercial.award')
        self.hidden={'Count'}
        with self.assertRaises(DomainError):masters._choose('A','award_items',query='absent',unit_id=self.unit)
    def test_integrity_and_capability_refusals_are_not_partial_success(self):
        self.add('Cost Center','A');self.add('Cost Center','B');self.corrupt={'B'}
        with self.assertRaises(DomainError) as error:masters._choose('A','cost_centers',limit=1,count_mode='exact')
        self.assertEqual(error.exception.code,'source_integrity')
        self.authorize.side_effect=DomainError('capability_denied','Denied',403);self.calls.clear()
        with self.assertRaises(DomainError):masters._choose('A','cost_centers')
        self.assertEqual(self.calls,[])
