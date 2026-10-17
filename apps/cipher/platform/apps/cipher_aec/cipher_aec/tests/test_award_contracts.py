"""Inactive PRJ-02 plan invariants; no award/native writer qualification."""
from copy import deepcopy
import unittest
from uuid import uuid4
from cipher_aec.api.errors import DomainError
from cipher_aec.awards.contracts import selected_sales_lines, wbs_nodes


class AwardPlans(unittest.TestCase):
    def setUp(self):
        self.ids=[str(uuid4()) for _ in range(4)]
        unit={'id':self.ids[3],'revision':1,'target':{'doctype':'UOM','name':'Synthetic quantity'},'fields':{'dimension':'count','precision':6}}
        self.issue={'status':'issued','native_lifecycle':'draft-snapshot','composition':{'currency':'USD'},'pricing':{'total':'35.85'},'selected_lines':[
            {'line':{'id':self.ids[0],'description':'Bound Item','selected':True,'item_code':'ITEM-A','quantity':'1.00','rate':'30.85','amount':'30.85','unit_id':unit['id'],'unit_revision':1},'unit':unit},
            {'line':{'id':self.ids[1],'description':'Explicit freeform mapping','selected':True,'item_code':None,'quantity':'2.5','rate':'2.00','amount':'5.00','unit_id':unit['id'],'unit_revision':1},'unit':unit}]}
        self.mappings=[{'proposal_line_id':self.ids[0],'item_code':'ITEM-A','delivery_date':'2026-12-16'},
                       {'proposal_line_id':self.ids[1],'item_code':'ITEM-B','delivery_date':'2026-12-17'}]

    def test_stable_selected_line_identity_exact_strings_and_explicit_freeform_mapping(self):
        before=deepcopy(self.issue)
        actual=selected_sales_lines(self.issue,list(reversed(self.mappings)),'2026-12-15')
        by_id={row['proposal_line_id']:row for row in actual}
        self.assertEqual(by_id[self.ids[0]]['quantity'],'1.00')
        self.assertEqual(by_id[self.ids[1]]['item_code'],'ITEM-B')
        self.assertEqual(by_id[self.ids[1]]['conversion_factor'],{'numerator':'1','denominator':'1'})
        self.assertEqual(actual,selected_sales_lines({**self.issue,'selected_lines':list(reversed(self.issue['selected_lines']))},self.mappings,'2026-12-15'))
        actual[0]['unit']['revision']=99
        self.assertEqual(self.issue,before)

    def test_missing_duplicate_or_foreign_selection_refuses(self):
        for mappings in (self.mappings[:1],[self.mappings[0],self.mappings[0]], [{**self.mappings[0],'proposal_line_id':self.ids[2]},self.mappings[1]]):
            with self.subTest(mappings=mappings),self.assertRaises(DomainError):
                selected_sales_lines(self.issue,mappings,'2026-12-15')

    def test_bound_item_price_override_backdated_delivery_and_stale_unit_refuse(self):
        for change in ({'item_code':'OTHER'},{'rate':'0.01'},{'delivery_date':'2026-12-14'}):
            with self.subTest(change=change),self.assertRaises(DomainError):
                selected_sales_lines(self.issue,[{**self.mappings[0],**change},self.mappings[1]],'2026-12-15')
        wrong=deepcopy(self.issue);wrong['selected_lines'][0]['unit']['revision']=2
        with self.assertRaises(DomainError):selected_sales_lines(wrong,self.mappings,'2026-12-15')
        wrong=deepcopy(self.issue);wrong['pricing']['total']='35.84'
        with self.assertRaises(DomainError):selected_sales_lines(wrong,self.mappings,'2026-12-15')

    def test_wbs_requires_same_plan_parent_leaf_integrity_and_no_cycle(self):
        root={'id':self.ids[0],'code':'01','parent':None,'title':'Scope','is_leaf':False}
        leaf={'id':self.ids[1],'code':'01.01','parent':root['id'],'title':'Work','is_leaf':True}
        self.assertEqual(wbs_nodes([leaf,root]),sorted([root,leaf],key=lambda row:row['id']))
        for nodes in ([root,{**leaf,'parent':self.ids[2]}],[{**root,'is_leaf':True},leaf],[{**root,'parent':leaf['id']},{**leaf,'is_leaf':False}],[root,{**leaf,'code':root['code']}]):
            with self.subTest(nodes=nodes),self.assertRaises(DomainError):wbs_nodes(nodes)
