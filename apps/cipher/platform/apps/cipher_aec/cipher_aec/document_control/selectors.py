"""Bounded current Project people for documentary recipients."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_options,decode_cursor,page_result,signing_secret
from cipher_aec.governance.context import current_actor,require_project,authority_fingerprint
from . import contracts as rules

def people(company,project,limit=25,cursor=None,count_mode='none'):
    """Current scoped identities, not an unfiltered native User directory."""
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if limit>100 or count_mode!='none':rules.fail('Use a bounded people page with no total.','paging')
    actor=current_actor();require_project(company,project,ability=rules.READ,actor=actor)
    scope={'route':'document.control.people.v1','company':company,'project':project,'limit':limit,'actor':actor.person_id,'user':actor.user,'authority':authority_fingerprint(actor,company,project)}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None;items=[];last_visible=None;scanned=0
    while len(items)<=limit:
        where="b.active=1 AND p.active=1 AND u.enabled=1 AND EXISTS (SELECT 1 FROM `tabCipher Project Duty` d WHERE d.person=b.person AND d.company=%s AND d.project=%s AND d.scope_type='Project' AND d.ability=%s AND d.active=1)"
        args=[company,project,rules.READ]
        if last:where+=' AND (b.person>%s OR (b.person=%s AND b.user>%s))';args.extend([last[0],last[0],last[1]])
        rows=frappe.db.sql('SELECT b.user,b.person,p.display_name FROM `tabCipher Identity Binding` b JOIN `tabCipher Person` p ON p.name=b.person JOIN `tabUser` u ON u.name=b.user WHERE '+where+' ORDER BY b.person,b.user LIMIT 25',args,as_dict=True)
        if not rows:break
        for row in rows:
            scanned+=1
            if scanned>500:raise DomainError('engineering_list_limit','The bounded people authorization scan exceeded its scope.',422)
            last=[row.person,row.user]
            try:
                person=current_actor(row.user)
                if person.person_id!=row.person:continue
                require_project(company,project,ability=rules.READ,actor=person)
            except DomainError as error:
                if error.status in (401,403,404):continue
                raise
            items.append({'user':row.user,'person':row.person,'display_name':row.display_name})
            if len(items)>limit:break
            last_visible=last
        if len(items)>limit or len(rows)<25:break
    return page_result(items[:limit],has_more=len(items)>limit,last=last_visible,scope=scope,limit=limit,count_mode='none',total=None)
