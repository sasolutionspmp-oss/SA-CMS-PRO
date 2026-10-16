"""Pure award-plan checks, inactive until the registered writer qualifies.

The supplied Issue must come from the authorized canonical commercial reader.
These checks neither authorize sources nor create masters, duties or an award.
"""
from copy import deepcopy
from decimal import Decimal

from cipher_aec.api.errors import DomainError
from cipher_aec.commercial.contracts import business_date, decimal, identifier, keys


def fail(message, code="invalid_award"):
    raise DomainError(code, message, 422)


def selected_sales_lines(issue, mappings, transaction_date):
    """Map the complete issued selection once, preserving exact source strings.

    Item eligibility, qualified current unit identity and native permissions are
    separately checked by the future adapter before supported controller save.
    No native row adjacency, current Quotation or caller-authored price is used.
    """
    business_date(transaction_date)
    if issue.get("status") != "issued" or issue.get("native_lifecycle") != "draft-snapshot":
        fail("Use an exact canonical immutable issued draft snapshot.")
    selected = issue.get("selected_lines")
    if type(selected) is not list or not 1 <= len(selected) <= 150:
        fail("The Issue requires a bounded nonempty selected-line snapshot.")
    if type(mappings) is not list or len(mappings) != len(selected):
        fail("Map every selected issued line exactly once.")
    by_id = {}
    for mapping in mappings:
        keys(mapping, ("proposal_line_id", "item_code", "delivery_date"), ("proposal_line_id", "item_code", "delivery_date"))
        source = identifier(mapping["proposal_line_id"])
        if source in by_id:
            fail("A selected source line cannot be adopted twice.")
        item = mapping["item_code"]
        if type(item) is not str or not item.strip() or len(item) > 140 or any(ord(c) < 32 for c in item):
            fail("Select an existing native sales Item for each issued line.")
        business_date(mapping["delivery_date"])
        if mapping["delivery_date"] < transaction_date:
            fail("Delivery cannot precede the order transaction date.")
        by_id[source] = mapping
    result, seen, total = [], set(), Decimal(0)
    for source in selected:
        line, unit = source["line"], source["unit"]
        line_id = identifier(line["id"])
        if line_id in seen or line_id not in by_id or line.get("selected") is not True:
            fail("Mappings must equal the stable selected Issue line set.")
        seen.add(line_id)
        mapping = by_id[line_id]
        if line.get("item_code") and mapping["item_code"] != line["item_code"]:
            fail("A native Item already bound by the Issue cannot be substituted.")
        if (unit.get("id") != line["unit_id"] or unit.get("revision") != line["unit_revision"]
                or unit.get("target", {}).get("doctype") != "UOM"):
            fail("The selected line must retain its exact qualified native unit.")
        quantity = decimal(line["quantity"], positive=True)
        decimal(line["rate"])
        amount = decimal(line["amount"])
        if quantity <= 0:
            fail("A selected quantity must be positive.")
        total += amount
        result.append({"proposal_line_id": line_id, "description": line["description"],
            "item_code": mapping["item_code"], "quantity": line["quantity"], "rate": line["rate"],
            "amount": line["amount"], "unit": deepcopy(unit), "currency": issue["composition"]["currency"],
            "conversion_factor": {"numerator": "1", "denominator": "1"},
            "delivery_date": mapping["delivery_date"]})
    if seen != set(by_id) or total != decimal(issue["pricing"]["total"]):
        fail("The adopted line set and total must equal the immutable issued selection.")
    return sorted(result, key=lambda row: row["proposal_line_id"])


def wbs_nodes(nodes):
    """Bounded stable WBS hierarchy; this creates no cost-code/type authority."""
    if type(nodes) is not list or not 1 <= len(nodes) <= 150:
        fail("Declare one through 150 stable WBS nodes.")
    by_id, codes = {}, set()
    for row in nodes:
        keys(row, ("id", "code", "parent", "title", "is_leaf"), ("id", "code", "parent", "title", "is_leaf"))
        identity = identifier(row["id"])
        if row["parent"] is not None:
            identifier(row["parent"])
        for name, maximum in (("code", 80), ("title", 200)):
            value = row[name]
            if type(value) is not str or not value.strip() or len(value) > maximum or any(ord(c) < 32 for c in value):
                fail("WBS codes and titles require bounded visible text.")
        if identity in by_id or row["code"] in codes or type(row["is_leaf"]) is not bool:
            fail("WBS identities/codes must be unique and leaf classification explicit.")
        by_id[identity] = deepcopy(row)
        codes.add(row["code"])
    parents = {row["parent"] for row in nodes if row["parent"] is not None}
    if parents - set(by_id):
        fail("WBS parents must belong to the same planned Project hierarchy.")
    for identity, row in by_id.items():
        if row["is_leaf"] == (identity in parents):
            fail("WBS leaf classification must match its actual children.")
        ancestry, current = set(), identity
        while current is not None:
            if current in ancestry:
                fail("WBS ancestry contains a cycle.")
            ancestry.add(current)
            current = by_id[current]["parent"]
    return sorted(by_id.values(), key=lambda row: row["id"])


def definition(value):
    """Closed authored intent; prices/costs/digests/destinations are server facts."""
    from .team import parse as team
    required=('issue_id','project_definition','native_order_definition','contract_definition','line_mappings','award_evidence',
        'party_correspondence','team','wbs_nodes','budget_allocations')
    keys(value,required,required)
    identifier(value['issue_id'])
    project=value['project_definition']
    fields=('project_name','expected_start_date','expected_end_date')
    keys(project,fields,fields)
    title=project['project_name']
    if type(title) is not str or not title.strip() or len(title)>140 or any(ord(c)<32 for c in title):fail('Supply a bounded explicit Project name.')
    for key in ('expected_start_date','expected_end_date'):business_date(project[key])
    if project['expected_end_date']<project['expected_start_date']:fail('Project end cannot precede its start.')
    order=value['native_order_definition']
    fields=('customer','transaction_date','delivery_date','selling_price_list')
    keys(order,fields,fields)
    for key in ('customer','selling_price_list'):
        if type(order[key]) is not str or not order[key].strip() or len(order[key])>140:fail('Select explicit existing native Customer and selling Price List.')
    business_date(order['transaction_date']);business_date(order['delivery_date'])
    if order['delivery_date']<order['transaction_date']:fail('Order delivery cannot precede its transaction date.')
    if type(value['line_mappings']) is not list or not 1<=len(value['line_mappings'])<=150:fail('Map the bounded complete selected line set.')
    citations=value['award_evidence']
    if type(citations) is not list or not 1<=len(citations)<=8:fail('Bind one through eight exact award-evidence citations.')
    for citation in citations:
        fields=('revision_id','page','excerpt_sha256','source_sha256','purpose','permission_basis')
        keys(citation,fields,fields)
        if type(citation['revision_id']) is not str or not 1<=len(citation['revision_id'])<=140 or type(citation['page']) is not int or citation['page']<1:fail('Use an exact canonical award citation.')
        import re
        if any(type(citation[k]) is not str or not re.fullmatch('[a-f0-9]{64}',citation[k]) for k in ('excerpt_sha256','source_sha256')):fail('Bind exact source and excerpt checksums.')
        for key in ('purpose','permission_basis'):
            if type(citation[key]) is not str or not citation[key].strip() or len(citation[key])>2000:fail('State the evidence purpose and permission basis.')
    correspondence=value['party_correspondence']
    if correspondence is not None:
        keys(correspondence,('lead','customer','explanation'),('lead','customer','explanation'))
        if any(type(v) is not str or not v.strip() or len(v)>2000 for v in correspondence.values()):fail('Bind the explicit existing Lead-to-Customer correspondence and explanation.')
    if type(value['wbs_nodes']) is not list or not 1<=len(value['wbs_nodes'])<=500 or type(value['budget_allocations']) is not list or not 1<=len(value['budget_allocations'])<=5030:fail('Supply bounded explicit WBS and accepted-cost mappings.')
    return {**deepcopy(value),'team':team(value['team'])}
