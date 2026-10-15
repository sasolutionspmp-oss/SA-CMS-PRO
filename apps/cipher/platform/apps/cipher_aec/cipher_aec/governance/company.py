"""Company aggregate reads; never interpret an absent Project as a wildcard."""
import frappe

from cipher_aec.api.contracts import digest
from cipher_aec.api.paging import decode_cursor, page_options, page_result, signing_secret
from cipher_aec.governance.context import company_authority_fingerprint, current_actor, require_company
from cipher_aec.governance.history import present_event


def history(company, limit=50, cursor=None, count_mode="none"):
    actor = current_actor()
    require_company(company, actor=actor)
    limit, cursor, count_mode = page_options(limit, cursor, count_mode)
    scope = {"scope_type": "Company", "company": company, "user": actor.user, "person": actor.person_id,
        "collection": "company_history", "authority": company_authority_fingerprint(actor, company)}
    last = decode_cursor(cursor, secret=signing_secret(), scope=scope) if cursor else None
    from .history_listing import list_visible
    return list_visible(company=company, project=None, scope_type="Company", actor=actor,
        scope=scope, limit=limit, last=last, count_mode=count_mode)
