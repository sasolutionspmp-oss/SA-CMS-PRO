"""Bounded authorization-first history paging for either explicit scope."""
import frappe
from cipher_aec.api.paging import page_result
from cipher_aec.api.errors import DomainError
from .history import present_event
from .history_access import readable

# Reads are deliberately bounded even for opt-in exact counts. If permissions
# cannot be evaluated completely within this boundary, expose no partial result.
MAX_SCAN = 10000
CHUNK_SIZE = 200


def list_visible(*, company, project, scope_type, actor, scope, limit, last, count_mode):
    where = "company=%s AND scope_type=%s"
    base = [company, scope_type]
    if scope_type == "Company":
        where += " AND (project IS NULL OR project='')"
    else:
        where += " AND project=%s"
        base.append(project)
    if scope_type == 'Project':
        from cipher_aec.quality_safety.privacy import query as incident_source_query
        docs = incident_source_query('Cipher Document')
        revisions = incident_source_query('Cipher Document Revision')
        rights_docs = docs.replace('`tabCipher Document`.`name`', '`tabCipher Source Rights Revision`.`parent_id`')
        where += " AND (subject_type!='Cipher Document' OR subject_id IN (SELECT name FROM `tabCipher Document` WHERE " + docs + "))"
        where += " AND (subject_type!='Cipher Document Revision' OR subject_id IN (SELECT name FROM `tabCipher Document Revision` WHERE " + revisions + "))"
        where += " AND (subject_type!='Cipher Source Rights Revision' OR subject_id IN (SELECT name FROM `tabCipher Source Rights Revision` WHERE " + rights_docs + "))"
    def visible(start=None):
        seek, scanned = start, 0
        while True:
            clause, values = where, list(base)
            if seek:
                clause += " AND (creation<%s OR (creation=%s AND name<%s))"
                values.extend((seek[0],seek[0],seek[1]))
            fields, selection_values = "name,creation", []
            if count_mode == "exact" and last:
                # Count the complete visible set while selecting the page using
                # the very same native datetime/name keyset predicate. Do not
                # compare timestamp strings or change the database tie order.
                fields += ", (creation<%s OR (creation=%s AND name<%s)) AS after_cursor"
                selection_values.extend((last[0],last[0],last[1]))
            rows = frappe.db.sql("SELECT " + fields + " FROM `tabCipher History Event` WHERE " + clause + " ORDER BY creation DESC,name DESC LIMIT %s", (*selection_values,*values,CHUNK_SIZE+1), as_dict=True)
            chunk = rows[:CHUNK_SIZE]
            for row in chunk:
                scanned += 1
                if scanned > MAX_SCAN:
                    raise DomainError("history_authorization_limit", "This history requires a narrower authorized export before it can be listed completely.", 409)
                event = frappe.get_doc("Cipher History Event",row.name)
                if readable(event, actor, company, project):
                    yield row,event
            if len(rows) <= CHUNK_SIZE:
                return
            seek = [str(chunk[-1].creation),chunk[-1].name]
    selected = []
    total = None
    if count_mode == "exact":
        total = 0
        for row,event in visible():
            total += 1
            if len(selected) <= limit and (not last or row.after_cursor):
                selected.append((row,event))
    else:
        for row,event in visible(last):
            selected.append((row,event))
            if len(selected)>limit:
                break
    page = selected[:limit]
    return page_result([present_event(event) for _,event in page], has_more=len(selected)>limit,
        last=[str(page[-1][0].creation),page[-1][0].name] if page else None,
        scope=scope, limit=limit, count_mode=count_mode, total=total)
