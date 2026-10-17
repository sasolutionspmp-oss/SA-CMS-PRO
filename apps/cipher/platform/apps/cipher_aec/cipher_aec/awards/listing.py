"""Bounded native keyset lists; counts/cursors follow exact per-row authority."""
import frappe
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import decode_cursor,page_options,page_result,signing_secret
from cipher_aec.governance.context import company_authority_fingerprint

CHUNK=100
MAX_SCAN=2000


def listed(*,company,actor,kind,reader,query='',limit=50,cursor=None,count_mode='none'):
    """Only the two literal inventories below may select a table or SQL fields."""
    limit,cursor,count_mode=page_options(limit,cursor,count_mode)
    if kind=='handoff':
        table='Cipher Award Handoff';where='company=%s AND (project IS NULL OR project=\'\')';args=[company]
        if query:raise DomainError('invalid_search','Handoff search is not exposed.',422)
    elif kind=='person':
        table='Cipher Person';where="active=1 AND identity_kind='Human'";args=[]
        if query:
            escaped=query.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')
            where+=' AND (name LIKE %s OR display_name LIKE %s)';args.extend(('%'+escaped+'%','%'+escaped+'%'))
    else:raise RuntimeError('Unregistered award inventory')
    scope={'list':'award.'+kind,'company':company,'person':actor.person_id,'user':actor.user,
        'authority':company_authority_fingerprint(actor,company),'query':query,'count_mode':count_mode}
    last=decode_cursor(cursor,secret=signing_secret(),scope=scope) if cursor else None
    seek=None if count_mode=='exact' else last
    scanned=0;total=0;selected=[]
    while True:
        conditions=where;values=list(args)
        if seek:
            conditions+=' AND (creation<%s OR (creation=%s AND name<%s))';values.extend((seek[0],seek[0],seek[1]))
        fields='name,creation';selection=[]
        if last and count_mode=='exact':
            fields+=', (creation<%s OR (creation=%s AND name<%s)) AS after_cursor';selection.extend((last[0],last[0],last[1]))
        rows=frappe.db.sql('SELECT '+fields+' FROM `tab'+table+'` WHERE '+conditions+' ORDER BY creation DESC,name DESC LIMIT %s',
            (*selection,*values,CHUNK+1),as_dict=True)
        chunk=rows[:CHUNK]
        for row in chunk:
            scanned+=1
            if scanned>MAX_SCAN:raise DomainError('authorization_scan_limit','Narrow this award inventory before listing it.',409)
            try:value=reader(row.name)
            except DomainError as error:
                if error.status in {403,404}:continue
                raise
            total+=1
            if count_mode!='exact' or not last or row.after_cursor:
                if len(selected)<=limit:selected.append((row,value))
            if count_mode=='none' and len(selected)>limit:break
        if count_mode=='none' and len(selected)>limit or len(rows)<=CHUNK:break
        seek=[str(chunk[-1].creation),chunk[-1].name]
    page=selected[:limit]
    return page_result([value for _,value in page],has_more=len(selected)>limit,
        last=[str(page[-1][0].creation),page[-1][0].name] if page else None,scope=scope,limit=limit,count_mode=count_mode,
        total=total if count_mode=='exact' else None)
