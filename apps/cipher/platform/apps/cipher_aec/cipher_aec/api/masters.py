"""Fixed, read-only native master choices with exact Company/native authority.

Candidates are scanned in bounded native-ID order. Only currently authorized
rows contribute to a count, page or public cursor; an incomplete scan fails.
"""
import frappe
from cipher_aec.api.contracts import digest, text, version_of
from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import decode_cursor, page_options, page_result, signing_secret
from cipher_aec.governance.context import current_actor, require_company, company_authority_fingerprint
from cipher_aec.commercial.native import party, require_native
from cipher_aec.estimating.units import currency_policy, qualified
from .transport import endpoint

MAX_SCAN = 2000
CHUNK = 200


def _choose(company, selector, *, query="", limit=50, cursor=None, count_mode="none", party_type=None, currency=None, dimension=None, unit_id=None):
    actor = current_actor()
    company_doc = require_company(company, actor=actor)
    query = text(query, "Search", 80, required=False).strip()
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    company_currency = company_doc.default_currency
    if not company_currency:
        raise DomainError("currency_setup_required", "Configure the Company's native base currency first.", 409)
    if selector == "parties":
        if party_type not in {"Customer", "Lead"}:
            raise DomainError("invalid_party_type", "Select Customer or Lead.", 422)
        doctype = party_type
    else:
        doctype = {"price_lists":"Price List", "units":"UOM", "currencies":"Currency", "items":"Item"}[selector]
    if selector == "price_lists" and currency not in {None, "", company_currency}:
        raise DomainError("currency_unsupported", "Commercial drafts currently use the Company's native base currency.", 422)
    if selector == "price_lists":
        require_native("Currency", company_currency, actor)
        currency_policy(company_currency)
    if dimension is not None and dimension not in {"count", "length", "area", "volume", "mass", "time", "labor_time", "equipment_time"}:
        raise DomainError("invalid_dimension", "Select a supported qualified unit dimension.", 422)
    unit_name = qualified(unit_id)["target"]["name"] if unit_id else None
    if unit_name:
        require_native("UOM", unit_name, actor)
    # Role and User Permission revisions invalidate a cursor after native authority
    # changes, in addition to per-item checks on every request.
    authority = {"user":str(frappe.db.get_value("User", actor.user, "modified")),
        "roles":frappe.get_roles(actor.user),
        "permissions":frappe.db.sql("SELECT name,allow,for_value,applicable_for,modified FROM `tabUser Permission` WHERE user=%s ORDER BY name",(actor.user,),as_dict=True)}
    scope = {"selector":selector,"company":company,"person":actor.person_id,"user":actor.user,
        "authority":company_authority_fingerprint(actor,company),"native_authority":digest(frappe.as_json(authority)),
        "company_currency":company_currency,"count_mode":count_mode,"query":query,"party_type":party_type,"currency":currency,"dimension":dimension,"unit_id":unit_id}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    visible = []
    seek = ""
    scanned = 0
    while True:
        conditions, args = ["name>%s"], [seek]
        if query:
            conditions.append("name LIKE %s")
            args.append("%"+query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")+"%")
        rows = frappe.db.sql("SELECT name FROM `tab"+doctype+"` WHERE "+" AND ".join(conditions)+" ORDER BY name LIMIT %s",(*args,CHUNK),as_dict=True)
        scanned += len(rows)
        if scanned > MAX_SCAN:
            raise DomainError("authorization_scan_limit", "Narrow the native master search before listing more choices.", 409)
        for row in rows:
            try:
                doc = party(doctype,row.name,company,actor) if selector == "parties" else require_native(doctype,row.name,actor)
                value = {"id":doc.name,"label":doc.name,"kind":doctype,"version":version_of(doc)}
                if selector == "parties":
                    if doc.get("disabled"):
                        continue
                    value["label"] = doc.get("customer_name") or doc.get("lead_name") or doc.name
                elif selector == "units":
                    if not doc.enabled or not doc.get("cipher_unit_id"):
                        continue
                    unit = qualified(doc.cipher_unit_id)
                    if dimension and unit["fields"]["dimension"] != dimension:
                        continue
                    value.update(unit_id=unit["id"],revision=unit["revision"],dimension=unit["fields"]["dimension"],precision=unit["fields"]["precision"])
                elif selector == "currencies":
                    if not doc.enabled:
                        continue
                    value["exponent"] = currency_policy(doc.name)["currency_exponent"]
                elif selector == "price_lists":
                    if not doc.enabled or not doc.selling or doc.currency != company_currency:
                        continue
                    require_native("Currency",doc.currency,actor)
                    currency_policy(doc.currency)
                    value["currency"] = doc.currency
                elif selector == "items":
                    if doc.disabled or company not in {r.company for r in doc.item_defaults} or unit_name and doc.stock_uom != unit_name:
                        continue
                    uom = require_native("UOM",doc.stock_uom,actor)
                    if not uom.get("cipher_unit_id"):
                        continue
                    unit = qualified(uom.cipher_unit_id)
                    value.update(label=doc.item_name or doc.name,stock_uom=doc.stock_uom,unit_id=unit["id"],revision=unit["revision"])
                visible.append(value)
            except DomainError as error:
                if error.status in {403,404} or selector == "currencies" and error.code == "currency_setup_required":
                    continue
                raise
        if len(rows) < CHUNK:
            break
        seek = rows[-1].name
    selected = [value for value in visible if not last or value["id"] > last[1]]
    page = selected[:limit]
    return {**page_result(page,has_more=len(selected)>limit,last=[page[-1]["id"],page[-1]["id"]] if page else None,
        scope=scope,limit=limit,count_mode=count_mode,total=len(visible) if count_mode=="exact" else None),"company_currency":company_currency}

@endpoint()
def parties(company, party_type, query="", limit=50, cursor=None, count_mode="none"):
    return _choose(company,"parties",party_type=party_type,query=query,limit=limit,cursor=cursor,count_mode=count_mode)

@endpoint()
def price_lists(company, query="", currency=None, limit=50, cursor=None, count_mode="none"):
    return _choose(company,"price_lists",currency=currency,query=query,limit=limit,cursor=cursor,count_mode=count_mode)

@endpoint()
def units(company, query="", dimension=None, limit=50, cursor=None, count_mode="none"):
    return _choose(company,"units",dimension=dimension,query=query,limit=limit,cursor=cursor,count_mode=count_mode)

@endpoint()
def currencies(company, query="", limit=50, cursor=None, count_mode="none"):
    return _choose(company,"currencies",query=query,limit=limit,cursor=cursor,count_mode=count_mode)

@endpoint()
def items(company, query="", unit_id=None, limit=50, cursor=None, count_mode="none"):
    return _choose(company,"items",unit_id=unit_id,query=query,limit=limit,cursor=cursor,count_mode=count_mode)
