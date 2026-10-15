"""Company inbox paging with fresh full presentation and one exact traversal."""
import frappe

from cipher_aec.api.errors import DomainError
from cipher_aec.api.paging import page_result

CHUNK_SIZE = 200
MAX_SCAN = 10000


def list_company_packets(*, company, actor, record, allowed_actions, scope, limit, last, count_mode):
    # Caller has resolved current Company authority, the literal action catalog
    # and the signed cursor before opening its explicit read-only graph root.
    from .approvals import _load, present

    def visible(start=None):
        seek, scanned = start, 0
        while True:
            where = "company=%s AND scope_type='Company' AND (project IS NULL OR project='') AND action IN (" + ",".join(["%s"] * len(allowed_actions)) + ")"
            values = [company, *allowed_actions]
            if seek:
                where += " AND (creation<%s OR (creation=%s AND name<%s))"
                values.extend((seek[0], seek[0], seek[1]))
            fields, selection_values = "name,creation", []
            if count_mode == "exact" and last:
                # SQL owns datetime precision and native name collation both
                # for page selection and for continuing the full count scan.
                fields += ", (creation<%s OR (creation=%s AND name<%s)) AS after_cursor"
                selection_values.extend((last[0], last[0], last[1]))
            rows = frappe.db.sql("SELECT " + fields + " FROM `tabCipher Approval Packet` WHERE " + where
                + " ORDER BY creation DESC,name DESC LIMIT %s", (*selection_values, *values, CHUNK_SIZE + 1), as_dict=True)
            chunk = rows[:CHUNK_SIZE]
            for row in chunk:
                scanned += 1
                if scanned > MAX_SCAN:
                    raise DomainError("authorization_scan_limit", "Narrow this approval scope before listing it.", 409)
                try:
                    value = present(_load(company, None, row.name, scope_type="Company"), record, actor)
                except DomainError as error:
                    if error.status in {401, 403, 404}:
                        continue
                    raise
                yield row, value
            if len(rows) <= CHUNK_SIZE:
                return
            seek = [str(chunk[-1].creation), chunk[-1].name]

    selected, total = [], None
    if count_mode == "exact":
        total = 0
        for row, value in visible():
            total += 1
            if len(selected) <= limit and (not last or row.after_cursor):
                selected.append((row, value))
    else:
        for row, value in visible(last):
            selected.append((row, value))
            if len(selected) > limit:
                break
    page = selected[:limit]
    return page_result([value for _, value in page], has_more=len(selected) > limit,
        last=[str(page[-1][0].creation), page[-1][0].name] if page else None,
        scope=scope, limit=limit, count_mode=count_mode, total=total)
