"""Opt-in real-storage generated-source union proof, using existing identities.

Never canonical fresh-site auto-discovery. No User/Auth/password/role writes,
provider/model, external delivery, or existing Company fixture mutation.
"""
from copy import deepcopy
from pathlib import Path
from uuid import uuid4
import json


def _save(name, value):
    import os
    import frappe
    base = Path(frappe.get_site_path("private", "cipher-fixtures"))
    path = base / name
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as stream:
        json.dump(value, stream, indent=2, default=str)
    return str(path.resolve())


def _load(path):
    import frappe
    from cipher_aec.tests.test_company_chain_acceptance import _administrator
    _administrator()
    path = Path(path).resolve()
    if not path.is_relative_to(Path(frappe.get_site_path("private", "cipher-fixtures")).resolve()) or not path.name.startswith("est-generated-"):
        raise RuntimeError("Only the explicit isolated generated-source fixture is supported")
    value = json.loads(path.read_text())
    if not value["company"].startswith("EST generated Company C "):
        raise RuntimeError("The isolated Company scope is missing")
    return value




def _source_snapshot():
    import hashlib
    base = Path(__file__).parents[1]
    paths = []
    for domain in ("estimating", "takeoff", "documents", "commercial"):
        paths.extend((base / domain).glob("*.py"))
    paths.extend(base / "governance" / name for name in (
        "commands.py", "approvals.py", "domain_approvals.py", "context.py", "history.py", "company.py", "permissions.py",
        "controllers.py", "history_access.py", "history_listing.py", "approval_listing.py"))
    paths.extend(base / "api" / name for name in ("contracts.py", "errors.py", "transport.py", "boundary.py", "company.py", "company_approvals.py", "paging.py"))
    paths.extend(base / "migrations" / name for name in ("contracts.py", "validation.py", "export.py"))
    paths.extend((base / "cipher_estimating").rglob("*.py"))
    for doctype in ("cipher_command_receipt", "cipher_history_event", "cipher_approval_packet", "cipher_approval_decision", "cipher_approval_consumption", "cipher_approval_policy_revision"):
        paths.extend((base / "cipher_governance" / "doctype" / doctype).glob("*.py"))
    paths.extend((base / "hooks.py", base / "tests" / "test_company_chain_acceptance.py"))
    paths.append(Path(__file__))
    return {str(path.relative_to(base)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(set(paths))}

def _timed_rpc(fixture, *, phase_profile=False):
    """Per-call counters preserve ordinary commits/rollback and authority."""
    import os
    import time
    import frappe
    from contextlib import contextmanager, ExitStack
    from unittest.mock import patch
    from cipher_aec.tests.test_company_chain_acceptance import NativeCompanyRPC
    path = Path(frappe.get_site_path("private", "cipher-fixtures", "est-generated-timing-" + uuid4().hex + ".jsonl"))
    class TimedRPC(NativeCompanyRPC):
        def __init__(self, value):
            super().__init__(value)
            self.timings = []
            self.source_snapshot = _source_snapshot()
            self.timing_path = str(path)
            self.timing_fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
        def invoke(self, method, values=None, expected_codes=()):
            return self._observe(method, lambda: super(TimedRPC, self).invoke(method, values, expected_codes))
        def observe_read(self, label, callback):
            return self._observe(label, callback, no_locks=True, seconds_limit=8, sql_limit=10000)
        def _observe(self, method, callback, *, no_locks=False, seconds_limit=30, sql_limit=50000):
            count = 0
            from cipher_aec.documents import storage, provenance
            from cipher_aec.governance import commands
            logical_stats = []
            phase_stack, phase_children, phase_counts = [], [], {}
            def profile(function, label, actor_position=None):
                from functools import wraps
                @wraps(function)
                def wrapped(*args, **kwargs):
                    actor = kwargs.get("actor")
                    if actor is None and actor_position is not None and len(args) > actor_position:
                        actor = args[actor_position]
                    user = getattr(actor, "user", None)
                    role = next((name for name, value in fixture["users"].items() if value["user"] == user), "request-context")
                    key = label + ":" + role + (":locked" if kwargs.get("lock") else ":read")
                    item = phase_counts.setdefault(key, {"calls": 0, "exclusive_sql": 0, "inclusive_sql": 0, "inclusive_seconds": 0.0, "exclusive_seconds": 0.0})
                    item["calls"] += 1
                    phase_stack.append(key)
                    phase_children.append(0.0)
                    began = time.monotonic()
                    try:
                        return function(*args, **kwargs)
                    finally:
                        elapsed = time.monotonic() - began
                        children = phase_children.pop()
                        item["inclusive_seconds"] += elapsed
                        item["exclusive_seconds"] += elapsed - children
                        phase_stack.pop()
                        if phase_children:
                            phase_children[-1] += elapsed
                return wrapped
            actual_operation = provenance.logical_operation
            @contextmanager
            def operation(*args, **kwargs):
                with actual_operation(*args, **kwargs):
                    try:
                        yield
                    finally:
                        snapshot = provenance.logical_operation_stats()
                        if snapshot is not None:
                            logical_stats.append(snapshot)
            disk_reads, byte_checks = 0, 0
            original_read, original_verify = storage.FrappeFileStorage.read, storage.verify_bytes
            sql = frappe.db.sql
            started = time.monotonic()
            def read(instance, *args, **kwargs):
                nonlocal disk_reads
                disk_reads += 1
                return original_read(instance, *args, **kwargs)
            def verify(*args, **kwargs):
                nonlocal byte_checks
                result = original_verify(*args, **kwargs)
                byte_checks += 1
                return result
            def counted(*args, **kwargs):
                nonlocal count
                statement = str(args[0]).strip().upper()
                if no_locks and "FOR UPDATE" in statement:
                    raise AssertionError("The bounded read-only phase profile attempted a row lock")
                # Frappe rollback starts its replacement empty transaction;
                # let cleanup finish after the observation budget is reached.
                cleanup = statement.startswith(("ROLLBACK", "COMMIT", "RELEASE SAVEPOINT", "START TRANSACTION"))
                if not cleanup and (time.monotonic() - started > seconds_limit or count >= sql_limit):
                    from cipher_aec.api.errors import DomainError
                    raise DomainError("fixture_profile_budget", f"The isolated native observation exceeded its fixed{seconds_limit}-second/{sql_limit}-query budget; no success qualified.", 503)
                count += 1
                if phase_stack:
                    phase_counts[phase_stack[-1]]["exclusive_sql"] += 1
                    for key in set(phase_stack):
                        phase_counts[key]["inclusive_sql"] += 1
                return sql(*args, **kwargs)
            status = "returned"
            try:
                with ExitStack() as stack:
                    stack.enter_context(patch.object(frappe.db, "sql", counted))
                    stack.enter_context(patch.object(storage.FrappeFileStorage, "read", read))
                    stack.enter_context(patch.object(storage, "verify_bytes", verify))
                    stack.enter_context(patch.object(provenance, "logical_operation", operation))
                    if getattr(commands, "logical_operation", None) is actual_operation:
                        stack.enter_context(patch.object(commands, "logical_operation", operation))
                    if phase_profile:
                        # Fixture-only attribution, not an authorization cache.
                        # Exclusive counts assign a query to its innermost
                        # instrumented phase; inclusive counts may overlap.
                        from cipher_aec.estimating import governance as est_gov, service as est_service, lockplan, sources as est_sources, units as est_units
                        from cipher_aec.takeoff import service as take_service
                        from cipher_aec.documents.core import DocumentService
                        from cipher_aec.commercial import native, output_sources
                        from cipher_aec.governance import context as authority
                        specs = [
                            (est_gov, "_facts", "estimate.current-facts", None),
                            (est_gov, "_historical", "estimate.original-facts", None),
                            (est_gov, "_pinned", "estimate.pinned-library", 3),
                            (est_service, "_scoped", "estimate.scoped-record", 4),
                            (est_service, "accepted_baseline_reference", "estimate.accepted-baseline", 3),
                            (est_units, "qualified", "authority.qualified-unit", None),
                            (est_units, "currency_policy", "authority.currency", None),
                            (take_service, "_read", "takeoff.scoped-record", 4),
                            (take_service, "_source", "takeoff.source", 3),
                            (take_service, "verified_binding_bundle", "takeoff.binding-bundle", 3),
                            (lockplan, "revision_plan", "estimate.plan-discovery", 1),
                            (provenance, "source_plan", "document.plan-discovery", 2),
                            (provenance, "node_manifest", "document.exact-node-facts", 1),
                            (provenance, "authorize", "document.producer-authority", 1),
                            (DocumentService, "_scope", "document.current-scope", None),
                            (est_sources, "verify", "estimate.citations", 3),
                            (est_sources, "verify_groups", "estimate.builder-citation-batch", 3),
                            (est_sources, "verify_native_rates", "estimate.native-sources", 3),
                            (authority, "require_company", "authority.company", None),
                            (native, "require_native", "authority.native-master", 2),
                            (output_sources, "binding_plan", "producer.plan", 1),
                            (output_sources, "authorize_binding", "producer.original-authority", 1),
                        ]
                        for owner, attr, label, actor_position in specs:
                            stack.enter_context(patch.object(owner, attr, profile(getattr(owner, attr), label, actor_position)))
                    result = callback()
                    if isinstance(result, dict) and result.get("error_code"):
                        status = "denied:" + result["error_code"]
                    return result
            except BaseException as error:
                status = getattr(error, "code", type(error).__name__)
                raise
            finally:
                row = {"method": method, "role": self.role, "status": status,
                    "elapsed_seconds": round(time.monotonic() - started, 6), "sql_calls": count,
                    "actual_artifact_disk_reads": disk_reads, "successful_exact_byte_integrity_checks": byte_checks,
                    "logical_operation_counters": logical_stats,
                    **({"sql_phase_attribution": phase_counts, "profiling_overhead_in_elapsed": True} if phase_profile else {}),
                    "source_generation_stable": self.source_snapshot == _source_snapshot()}
                self.timings.append(row)
                os.write(self.timing_fd, (json.dumps(row) + "\n").encode()); os.fsync(self.timing_fd)
        def close(self):
            try:
                return super().close()
            finally:
                os.close(self.timing_fd)
    return TimedRPC(fixture)

def prepare_generated_fixture(private_manifest):
    """Supported native Company/master setup; existing identities only."""
    import frappe
    from cipher_aec.tests.test_company_chain_acceptance import _load_fixture
    from cipher_aec.governance.context import trusted_write, COMPANY_ABILITIES, current_actor
    from cipher_aec.install import _grant_company
    from cipher_aec.estimating.company_service import register_unit
    existing = _load_fixture(private_manifest)
    marker = uuid4().hex[:12]
    company = "EST generated Company C " + marker
    before_projects = frappe.db.count("Project")
    with trusted_write():
        doc = frappe.get_doc({"doctype": "Company", "company_name": company, "abbr": "EG" + marker[:6], "country": "United States", "default_currency": "USD"}).insert(ignore_permissions=True)
        frappe.get_doc({"doctype": "Fiscal Year", "year": "EST generated 2026 " + marker, "year_start_date": "2026-01-01", "year_end_date": "2026-12-31", "companies": [{"company": company}]}).insert(ignore_permissions=True)
        for person in (current_actor().person_id, existing["users"]["author"]["person"]):
            for ability in sorted(COMPANY_ABILITIES):
                _grant_company(person, company, ability)
        for ability in ("company.read", "commercial.read", "document.read", "estimate.read", "approval.decide"):
            _grant_company(existing["users"]["reviewer"]["person"], company, ability)
        template = frappe.get_doc("Customer", existing["native"]["a"]["customer"])
        customer = frappe.get_doc({"doctype": "Customer", "customer_name": "EST generated customer " + marker, "customer_type": "Company", "customer_group": template.customer_group, "territory": template.territory,
            "accounts": [{"company": company, "account": doc.default_receivable_account}]}).insert(ignore_permissions=True)
        template_supplier = frappe.get_doc("Supplier", existing["native"]["a"]["supplier"])
        supplier = frappe.get_doc({"doctype": "Supplier", "supplier_name": "EST generated supplier " + marker, "supplier_type": "Company", "supplier_group": template_supplier.supplier_group,
            "accounts": [{"company": company, "account": doc.default_payable_account}]}).insert(ignore_permissions=True)
        native_units = {}
        for name in ("count", "sf", "sy", "ft"):
            native_units[name] = frappe.get_doc({"doctype": "UOM", "uom_name": "EST generated " + marker + " " + name, "symbol": name + marker, "enabled": 1, "must_be_whole_number": 0}).insert(ignore_permissions=True).name
        group = frappe.get_doc("Item", existing["native"]["a"]["item"]).item_group
        item = frappe.get_doc({"doctype": "Item", "item_code": "EST-GENERATED-" + marker, "item_name": "EST generated producer " + marker, "item_group": group, "stock_uom": native_units["count"], "is_stock_item": 0, "item_defaults": [{"company": company}]}).insert(ignore_permissions=True)
        price_list = frappe.get_doc({"doctype": "Price List", "price_list_name": "EST generated selling " + marker, "currency": "USD", "enabled": 1, "selling": 1}).insert(ignore_permissions=True)
    frappe.db.commit()
    qualified = {}
    for name, dimension in (("count", "count"), ("sf", "area"), ("sy", "area"), ("ft", "length")):
        qualified[name] = register_unit(company, str(uuid4()), native_units[name], dimension, 6)["unit"]
    frappe.db.commit()
    fixture = deepcopy(existing)
    fixture.update(company=company, fixture_id="company-chain-" + marker, qualified_unit=qualified["count"], native_unit=native_units["count"], units=qualified, native_units=native_units,
        native={"a": {"customer": customer.name, "supplier": supplier.name, "item": item.name, "price_list": price_list.name}, "b": existing["native"]["b"]})
    assert frappe.db.count("Project") == before_projects and not frappe.db.count("Project", {"company": company})
    path = _save("est-generated-" + marker + ".secret.json", fixture)
    return {"private_fixture": path, "company": company, "native_units": native_units,
        "existing_identities_reused": True, "user_auth_role_writes": False, "project_created": False}


def prepare_generated_dag(private_fixture):
    """Three real producer PDFs: A, B→A, C→A+B (shared A node)."""
    import frappe
    from cipher_aec.api.contracts import digest
    from cipher_aec.tests.test_company_chain_acceptance import NativeCompanyRPC, drive_manual_estimate
    fixture = _load(private_fixture)
    rpc = _timed_rpc(fixture)
    try:
        context = drive_manual_estimate(rpc, fixture, "generated-source-producer-baseline")
        company = fixture["company"]
        baseline = context["accepted"]["effect"]["acceptance"]
        reference = {"acceptance_id": baseline["id"], "acceptance_digest": digest(baseline), "revision_id": context["calculated"]["revision"]["id"], "revision_digest": digest(context["calculated"]["revision"])}
        nodes, citations = [], []
        raw = {key: context["citation"][key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        for name, sources in (("A", [raw]), ("B", [0]), ("C", [0, 1])):
            refs = [citations[row] if type(row) is int else row for row in sources]
            composition = {"currency": "USD", "price_list": fixture["native"]["a"]["price_list"], "valid_till": "2026-12-01",
                "terms": "Explicit isolated generated union fixture; no distribution or award.",
                "sections": [{"id": str(uuid4()), "kind": "scope", "title": "Synthetic source " + name, "text": "Explicit nested producer source " + name}],
                "price_lines": [{"id": str(uuid4()), "description": "Explicit authored producer", "quantity": "1", "unit_id": fixture["qualified_unit"]["id"], "unit_revision": 1, "rate": "30.85", "item_code": fixture["native"]["a"]["item"], "alternate_group": None, "selected": True}],
                "source_references": [{**row, "purpose": "Exact nested producer source", "permission_basis": "Explicit authored synthetic fixture permission"} for row in refs], "estimate_reference": reference}
            rpc.login("author")
            made = rpc.invoke("cipher_aec.commercial.api.create_proposal", {"company": company, "pursuit_id": context["pursuit"]["id"], "composition": composition, "operation_id": str(uuid4())})
            revision = made["revision"]
            prepared = rpc.invoke("cipher_aec.commercial.api.prepare_proposal_output", {"company": company, "proposal_id": made["proposal"]["id"], "revision_id": revision["id"], "expected_revision_digest": digest(revision), "recipients": [{"name": "Synthetic reviewer", "email": "fixture@example.test", "organization": "Explicit isolated fixture"}], "cover": "Exact generated source " + name, "operation_id": str(uuid4())})["prepared_output"]
            citation = rpc.invoke("cipher_aec.documents.company_api.get_citation", {"company": company, "revision_id": prepared["revision_id"], "page": 1})
            nodes.append({"name": name, "prepared": prepared, "proposal": made["proposal"], "revision": revision})
            citations.append({key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")})
        result = {"company": company, "context": context, "nodes": nodes, "citations": citations, "calls": rpc.calls, "command_timings": rpc.timings, "timing_journal_path": rpc.timing_path,
            "qualification": "Actual native Frappe/ERPNext/MariaDB with explicit synthetic Sessions; not HTTP; no model/provider/distribution"}
        path = _save("est-generated-dag-" + uuid4().hex + ".json", result)
        return {"status": "passed", "private_dag": path, "company": company, "node_count": 3, "shared_dag_node": "A", "user_auth_role_writes": False, "live_model_qualified": False}
    finally:
        rpc.close()


def run_generated_union_acceptance(private_fixture, private_dag):
    """Actual Company pricing/conversion/basis/drawing/binding/approval union."""
    import base64
    import hashlib
    import os
    from contextlib import contextmanager
    from datetime import datetime, timezone
    from unittest.mock import patch
    import frappe
    from cipher_aec.api.contracts import digest
    from cipher_aec.estimating import lockplan, scopes, sources
    from cipher_aec.commercial import native
    from cipher_aec.estimating import units
    from cipher_aec.documents import provenance
    from cipher_aec.takeoff.geometry import FORMULA
    from cipher_aec.tests.test_company_chain_acceptance import NativeCompanyRPC, authored_company_inputs
    fixture = _load(private_fixture)
    dag = json.loads(Path(private_dag).read_text())
    company, q = fixture["company"], fixture["units"]
    if dag["company"] != company:
        raise RuntimeError("The generated nodes require the exact isolated Company")
    rpc = _timed_rpc(fixture)
    original_prepared, original_qualified, original_native = lockplan.prepared, units.qualified, native.require_native
    trace, acquisition, operations = [], [], []
    journal_path = Path(frappe.get_site_path("private", "cipher-fixtures", "est-generated-journal-" + uuid4().hex + ".jsonl"))
    journal_fd = os.open(journal_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
    def command(method, payload):
        values = {"company": company, "operation_id": str(uuid4()), **payload}
        entry = {"method": method, "payload": deepcopy(values)}
        os.write(journal_fd, (json.dumps(entry, sort_keys=True) + "\n").encode()); os.fsync(journal_fd)
        operations.append(entry)
        return values, rpc.invoke(method, values)
    def qualified(name, **kwargs):
        if kwargs.get("lock"):
            trace.append(("UOM", name))
        return original_qualified(name, **kwargs)
    def require_native(kind, name, actor, **kwargs):
        if kwargs.get("lock") and kind != "UOM":
            trace.append((kind, name))
        return original_native(kind, name, actor, **kwargs)
    @contextmanager
    def prepared(plan, actor, company, **kwargs):
        root = not lockplan.active_for(actor, company) and not provenance.has_prelocked()
        start = len(trace)
        with original_prepared(plan, actor, company, **kwargs) as admitted:
            if root:
                expected = [("UOM", name) for name in admitted["unit_ids"]] + [("Currency", name) for name in admitted["currencies"]] + [(row["doctype"], row["name"]) for row in admitted["native_refs"]]
                assert trace[start:] == expected, (trace[start:], expected)
                acquisition.append({"plan": deepcopy(admitted), "actual_native_lock_calls": deepcopy(trace[start:])})
            yield admitted
    docs, est, take, gov = "cipher_aec.documents.company_api.", "cipher_aec.estimating.company_api.", "cipher_aec.takeoff.company_api.", "cipher_aec.api.company_approvals."
    started = datetime.now(timezone.utc).isoformat()
    try:
        rpc.login("author")
        content = b"Explicit authored outer EUR quote: rate1.25 per square-foot. Nested USD producer PDFs are scope evidence only. No foreign-exchange conversion."
        _, uploaded = command(docs + "upload_document", {"title": "Outer EUR explicit quote", "filename": "outer-eur.txt", "content_base64": base64.b64encode(content).decode(), "byte_length": len(content), "sha256": hashlib.sha256(content).hexdigest()})
        citation = rpc.invoke(docs + "get_citation", {"company": company, "revision_id": uploaded["revision"]["id"], "page": 1})
        raw = {key: citation[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
        inputs = authored_company_inputs(fixture, citation, q["sf"]["id"])
        rate = {**inputs["rate"], "currency": "EUR", "rate_amount": "1.25", "source_citations": [raw, dag["citations"][0]], "item": None}
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True), patch.object(lockplan, "prepared", prepared), patch.object(units, "qualified", qualified), patch.object(native, "require_native", require_native):
            rate_args, result = command(est + "create_rate", {"rate": rate})
            rate_record = result["rate_source"]
            previous_conversion = frappe.db.sql("SELECT name FROM `tabCipher Unit Conversion` WHERE company=%s AND scope_type='Company' AND from_unit_id=%s AND to_unit_id=%s ORDER BY revision_number DESC LIMIT 1", (company, q["sy"]["id"], q["sf"]["id"]))
            conversion_args, result = command(est + "create_conversion", {"predecessor": previous_conversion[0][0] if previous_conversion else None, "definition": {"from_unit_id": q["sy"]["id"], "to_unit_id": q["sf"]["id"], "dimension": "area", "numerator": "9", "denominator": "1", "source": "Explicit rational area fixture, independent of document pricing currency"}, "source_citations": [dag["citations"][1]], "permission_basis": "Explicit synthetic source permission"})
            conversion = result["conversion"]
            _, result = command(est + "create_estimate", {"title": "Outer exact EUR estimate with nested USD scope", "currency": "EUR", "pricing_date": "2026-10-15", "pursuit_id": dag["context"]["pursuit"]["id"]})
            master = result["estimate"]
            line = {**inputs["line"], "quantity": {"amount": "200.000000", "unit_id": q["sf"]["id"], "precision": 6}, "rate_source_id": rate_record["id"]}
            calculate_args, calculated = command(est + "calculate_revision", {"estimate_id": master["id"], "expected_revision": None, "lines": [line], "adjustments": [], "conversion_ids": [conversion["id"]], "basis_description": "EUR pricing selected explicitly; nested USD producer documents provide scope evidence only; no FX", "basis_citations": [dag["citations"][2]]})
            revision = calculated["revision"]
            assert revision["total"] == {"amount": "250.00", "currency": "EUR"}
            snapshot_units = {row["id"] for row in calculated["calculation"]["inputs"]["unit_manifest"]["records"] if row["kind"] == "uom"}
            assert q["count"]["id"] not in snapshot_units
            selected_currency = calculated["calculation"]["inputs"]["currency"]
            assert selected_currency == "EUR"
            assert any(q["count"]["id"] in row["plan"]["unit_ids"] and row["plan"]["currencies"] == ["EUR", "USD"] and len(row["plan"]["generated_sources"]) == 3 for row in acquisition)
            _, result = command(take + "create_set", {"title": "Generated drawing reference", "discipline": "Explicit synthetic geometry", "drawing_package": "Exact generated PDF", "basis": "Authored reference anchors in stored PDF user space; no feature recognition or automatic model geometry"})
            takeoff_set = result["takeoff_set"]
            source = {"revision_id": dag["nodes"][2]["prepared"]["revision_id"], "source_sha256": dag["nodes"][2]["prepared"]["source_sha256"], "page": 1}
            definition = {"title": "Authored generated-PDF reference calibration", "coordinate_system": "pdf-user-space-v1", "anchors": [["100", "100"], ["200", "100"]], "known_distance": {"amount": "10", "unit_id": q["ft"]["id"], "precision": 6}, "relative_numeric_tolerance": "0.000000000001", "derived_units": [{"output_unit_id": q["sf"]["id"], "power": 2, "numerator": "1", "denominator": "1", "basis": "Explicit square foot relation", "source_citations": [dag["citations"][2]]}], "basis": "Explicit synthetic coordinate reference, no visual feature recognition", "formula_version": FORMULA}
            _, result = command(take + "create_calibration", {"takeoff_set": takeoff_set["id"], "source": source, "definition": definition, "conversion_ids": []})
            calibration = result["calibration"]
            _, result = command(gov + "request_action", {"action": "calibration.verify.v1", "subject_id": calibration["id"], "expected_version": digest(calibration)})
            packet = result["packet"]
            rpc.login("reviewer")
            command(gov + "decide_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Independent exact source/reference review"})
            rpc.login("author")
            command(gov + "execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]})
            measurement_definition = {"method": "calibrated", "calibration_id": calibration["id"], "geometry": {"type": "polygon", "points": [["100", "100"], ["300", "100"], ["300", "200"], ["100", "200"]]}, "result_unit_id": q["sf"]["id"], "kind": "area", "locator": "PDF page1 known authored rectangle100,100 to300,200", "reason": "Explicit synthetic coordinates, no automated geometry extraction", "result_precision": 6, "tolerance": "0.000001", "waste_fraction": "0", "formula_version": FORMULA, "depth": None}
            measurement_args, result = command(take + "create_measurement", {"takeoff_set": takeoff_set["id"], "source": source, "definition": measurement_definition, "conversion_ids": []})
            measurement = result["measurement"]
            assert measurement["result"]["quantity"]["amount"] == "200.000000"
            _, result = command(take + "bind_line", {"measurement_id": measurement["id"], "estimate_line_record": revision["line_record_ids"][0], "quantity_basis": "net-quantity-v1", "reason": "Subsequently attached exact geometry; original pricing snapshot preserved"})
            binding = result["binding"]
            _, result = command(gov + "request_action", {"action": "estimate.accept.v1", "subject_id": revision["id"], "expected_version": digest(revision)})
            packet = result["packet"]
            facts = packet["review_manifest"]["effect"]["facts"]
            assert len(facts["generated_sources"]) == 3
            assert {row["document_id"] for row in facts["generated_sources"]} == {row["prepared"]["document_id"] for row in dag["nodes"]}
            rpc.login("reviewer")
            command(gov + "decide_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Reviewed exact EUR pricing, full source DAG and independently verified geometry"})
            rpc.login("author")
            # Advance only producer A's native Quotation through supported COM.
            # Its original prepared revision and source bytes remain pinned.
            node = dag["nodes"][0]
            command("cipher_aec.commercial.api.save_proposal_revision", {"proposal_id": node["proposal"]["id"], "expected_revision": node["proposal"]["revision_number"], "expected_native_fingerprint": node["revision"]["native_fingerprint"], "composition": node["revision"]["composition"]})
            pending = rpc.invoke(gov + "read_packet", {"company": company, "packet_id": packet["id"]})
            assert pending["review_manifest"] == packet["review_manifest"]
            execute_args, accepted = command(gov + "execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]})
            baseline = accepted["effect"]["acceptance"]
            rpc.login("alias")
            for method, args, expected_key, expected_id in ((est + "calculate_revision", calculate_args, "revision", revision["id"]), (take + "create_measurement", measurement_args, "measurement", measurement["id"]), (gov + "execute_packet", execute_args, "effect", None)):
                replay = rpc.invoke(method, args)
                assert replay["operation"]["replayed"]
                if expected_id:
                    assert replay[expected_key]["id"] == expected_id
                else:
                    assert replay["effect"]["acceptance"] == baseline
        result = {"status": "passed", "started": started, "finished": datetime.now(timezone.utc).isoformat(), "company": company,
            "qualification": "Actual Frappe/ERPNext/MariaDB with explicit synthetic Sessions; not HTTP; authored geometry and exact stored generated PDFs",
            "revision": revision, "calculation": calculated["calculation"], "rate": rate_record, "conversion": conversion,
            "calibration": calibration, "measurement": measurement, "binding": binding, "packet": packet, "acceptance": baseline,
            "producer_dag": dag["nodes"], "lock_acquisitions": acquisition, "journal_path": str(journal_path), "operations": operations, "calls": rpc.calls, "command_timings": rpc.timings, "timing_journal_path": rpc.timing_path,
            "producer_only_native_quotation_successor_keeps_exact_pending_manifest": True,
            "producer_unit_absent_outer_snapshot": q["count"]["id"], "producer_currency_absent_outer_snapshot": "USD",
            "shared_dag_deduplicated": True, "canonical_successful_receipt_replays": 3,
            "live_model_qualified": False, "external_provider_qualified": False}
        path = _save("est-generated-union-" + uuid4().hex + ".json", result)
        return {"status": "passed", "private_result": path, "company": company, "total": revision["total"], "generated_nodes": 3, "lock_acquisitions": len(acquisition), "live_model_qualified": False}
    finally:
        os.close(journal_fd)
        rpc.close()


def run_original_receipt_after_private_binding(private_fixture, private_union):
    """Original successful receipt ignores later unselected private geometry."""
    import os
    import frappe
    from cipher_aec.api.contracts import digest
    from cipher_aec.estimating import sources
    from cipher_aec.governance.context import trusted_write
    from cipher_aec.tests.test_company_chain_acceptance import NativeCompanyRPC, company_history_inventory
    from unittest.mock import patch
    fixture = _load(private_fixture)
    union = json.loads(Path(private_union).read_text())
    company = fixture["company"]
    assert union["company"] == company
    rpc = _timed_rpc(fixture)
    est, take, gov = "cipher_aec.estimating.company_api.", "cipher_aec.takeoff.company_api.", "cipher_aec.api.company_approvals."
    journal = []
    marker = uuid4().hex
    path = Path(frappe.get_site_path("private", "cipher-fixtures", "est-generated-original-receipt-journal-" + marker + ".jsonl"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
    def command(method, payload, expected_codes=()):
        values = {"company": company, "operation_id": str(uuid4()), **payload}
        entry = {"method": method, "role": rpc.role, "payload": deepcopy(values)}
        journal.append(entry); os.write(fd, (json.dumps(entry) + "\n").encode()); os.fsync(fd)
        return values, rpc.invoke(method, values, expected_codes=expected_codes)
    def grant(revision):
        rpc.login("author")
        request, requested = command(gov + "request_action", {"action": "estimate.accept.v1", "subject_id": revision["id"], "expected_version": digest(revision)})
        packet = requested["packet"]
        rpc.login("reviewer")
        command(gov + "decide_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Independent synthetic exact-sources review"})
        rpc.login("author")
        return packet
    def duty(active):
        frappe.set_user("Administrator")
        rows = frappe.db.sql("SELECT name FROM `tabCipher Project Duty` WHERE scope_type='Company' AND company=%s AND person=%s AND ability='commercial.read'", (company, fixture["users"]["author"]["person"]))
        assert len(rows) == 1
        with trusted_write():
            record = frappe.get_doc("Cipher Project Duty", rows[0][0]); record.active = active; record.save(ignore_permissions=True)
        frappe.db.commit()
    history_observations = []
    def history(phase):
        from cipher_aec.api.errors import DomainError
        try:
            inventory = company_history_inventory(rpc, company)
        except DomainError as error:
            if error.code != "fixture_profile_budget":
                raise
            history_observations.append({"phase": phase, "status": "fixed-fixture-budget-reached", "qualified": False})
            return None
        history_observations.append({"phase": phase, "status": "returned", "total": inventory["total"]})
        return inventory
    outage = False
    try:
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True):
            rpc.login("author")
            raw = next(row for row in union["rate"]["source_citations"] if row["revision_id"] not in {node["prepared"]["revision_id"] for node in union["producer_dag"]})
            cite = {key: raw[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")}
            rate = {key: value for key, value in union["rate"]["rate"].items() if key not in {"id", "source_id", "revision", "predecessor"}}
            rate["source_citations"] = [cite]
            _, made = command(est + "create_rate", {"rate": rate})
            _, made_master = command(est + "create_estimate", {"title": "Historical original sources remain public to this actor " + marker[:8], "currency": "EUR", "pricing_date": "2026-10-15", "pursuit_id": None})
            master = made_master["estimate"]
            line = deepcopy(union["calculation"]["inputs"]["lines"][0]); line.update(line_id=str(uuid4()), rate_source_id=made["rate_source"]["id"])
            line["quantity"]["amount"] = "200"  # Exact equivalent of measured200.000000.
            body = {"estimate_id": master["id"], "expected_revision": None, "lines": [line], "adjustments": [], "conversion_ids": [], "basis_description": "Original raw source only; no Pursuit or generated source selected", "basis_citations": [cite]}
            calc_args, original = command(est + "calculate_revision", body)
            packet = grant(original["revision"])
            execute_args, accepted = command(gov + "execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]})
            baseline = accepted["effect"]["acceptance"]
            # Attach evidence AFTER original acceptance. It was never an input
            # or accepted dependency of the immutable original baseline.
            _, first_binding = command(take + "bind_line", {"measurement_id": union["measurement"]["id"], "estimate_line_record": original["revision"]["line_record_ids"][0], "quantity_basis": "net-quantity-v1", "reason": "Later evidence does not rewrite an accepted original manifest"})
            _, successor = command(est + "calculate_revision", {**body, "expected_revision": original["revision"]["id"]})
            _, next_binding = command(take + "bind_line", {"measurement_id": union["measurement"]["id"], "estimate_line_record": successor["revision"]["line_record_ids"][0], "quantity_basis": "net-quantity-v1", "reason": "Fresh acceptance must explicitly include generated geometry"})
            pending = grant(successor["revision"])
            _save("est-generated-original-receipt-prepared-" + marker + ".json", {
                "status": "committed-fixture-stages-not-yet-qualified", "company": company,
                "baseline": baseline, "original": original, "packet": packet,
                "successor": successor, "pending_packet": pending,
                "first_binding": first_binding, "next_binding": next_binding,
                "execute_args": execute_args, "calc_args": calc_args,
                "journal_path": str(path), "operations": journal,
                "source_snapshot": rpc.source_snapshot, "live_model_qualified": False})
            before = history("before-authority-outage")
            duty(0); outage = True
            rpc.login("author")
            assert rpc.invoke(est + "get_record", {"company": company, "kind": "acceptance", "record_id": baseline["id"]}) == baseline
            old_packet = rpc.invoke(gov + "read_packet", {"company": company, "packet_id": packet["id"]})
            assert old_packet["state"] == "Consumed"
            replay = rpc.invoke(gov + "execute_packet", execute_args)
            assert replay["operation"]["replayed"] and replay["effect"]["acceptance"] == baseline
            replay = rpc.invoke(est + "calculate_revision", calc_args)
            assert replay["operation"]["replayed"] and replay["revision"] == original["revision"]
            for operation in (execute_args["operation_id"], calc_args["operation_id"]):
                assert rpc.invoke("cipher_aec.api.company.operation", {"company": company, "operation_id": operation})["operation"]["replayed"]
            denied = {"not_found", "capability_denied"}
            rpc.invoke(take + "get_record", {"company": company, "kind": "measurement", "record_id": union["measurement"]["id"]}, expected_codes=denied)
            execute_pending, _ = command(gov + "execute_packet", {"packet_id": pending["id"], "manifest_hash": pending["manifest_hash"]}, expected_codes=denied)
            assert not frappe.db.exists("Cipher Estimate Acceptance", {"estimate_revision": successor["revision"]["id"]})
            hidden = history("during-authority-outage")
            if hidden is not None:
                visible_ids = {row["subject_id"] for row in hidden["items"]}
                assert baseline["id"] in visible_ids and packet["id"] in visible_ids
                assert union["measurement"]["id"] not in visible_ids
                assert first_binding["binding"]["id"] not in visible_ids and next_binding["binding"]["id"] not in visible_ids
                if before is not None:
                    assert hidden["total"] < before["total"]
            duty(1); outage = False
            rpc.login("author")
            restored_history = history("after-authority-restoration")
            if before is not None and restored_history is not None:
                assert restored_history["total"] == before["total"]
            completed = rpc.invoke(gov + "execute_packet", execute_pending)
            assert completed["effect"]["acceptance"]["estimate_revision"] == successor["revision"]["id"]
            replay = rpc.invoke(gov + "execute_packet", execute_pending)
            assert replay["operation"]["replayed"] and replay["effect"] == completed["effect"]
            assert frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": successor["revision"]["id"]}) == 1
            result = {"status": "passed", "company": company, "qualification": "Actual native Frappe/ERPNext/MariaDB with explicit synthetic Sessions; not HTTP",
                "original_baseline": baseline["id"], "original_revision": original["revision"]["id"], "later_binding": first_binding["binding"]["id"],
                "source_outage": "CompanyC author commercial.read only; original raw source estimate has no Pursuit/generated dependency",
                "original_packet_and_baseline_and_four_receipt_reads_remained_available": True,
                "later_generated_measurement_denied": True, "new_effect_denied_before_acceptance": True,
                "history_privacy_qualified": all(value is not None for value in (before, hidden, restored_history)),
                "history_counts": [value["total"] if value is not None else None for value in (before, hidden, restored_history)],
                "history_observations": history_observations,
                "same_persisted_execute_uuid_after_authority_restoration": execute_pending["operation_id"],
                "one_effect_then_same_uuid_receipt_replay": True, "company_duty_restored": True,
                "journal_path": str(path), "calls": rpc.calls, "command_timings": rpc.timings, "timing_journal_path": rpc.timing_path, "live_model_qualified": False}
            artifact = _save("est-generated-original-receipt-" + marker + ".json", result)
            return {"status": "passed", "private_result": artifact, "history_counts": result["history_counts"], "company_duty_restored": True}
    finally:
        if outage:
            duty(1)
        os.close(fd)
        rpc.close()


def profile_generated_sources(private_fixture, phase_budget_seconds=8):
    """Bounded read-only profiling; no Person/native FOR UPDATE acquisitions.

    Query and elapsed budgets abort profiling only, never relax product checks.
    This does not qualify a mutation or a transaction-bound authorization cache.
    """
    import time
    import frappe
    from unittest.mock import patch
    from cipher_aec.api.contracts import digest
    from cipher_aec.governance.context import current_actor
    from cipher_aec.estimating import lockplan, scopes, governance
    from cipher_aec.documents import provenance, service as docs
    from cipher_aec.commercial import output_sources
    fixture = _load(private_fixture)
    company = fixture["company"]
    checkpoint = json.loads(Path(frappe.get_site_path("private", "cipher-fixtures", "est-generated-interrupted-checkpoint.json")).read_text())
    request = checkpoint["last_attempt"]["payload"]
    if request["company"] != company or type(phase_budget_seconds) is not int or not 1 <= phase_budget_seconds <= 10:
        raise RuntimeError("Explicit bounded CompanyC profile required")
    class Budget(Exception): pass
    phases = []
    sql = frappe.db.sql
    def phase(name, effect):
        counts = {"queries": 0, "plan_calls": 0, "authorize_calls": 0, "binding_plan_calls": 0, "binding_authorize_calls": 0}
        start = time.monotonic()
        def query(*args, **kwargs):
            if time.monotonic() - start > phase_budget_seconds or counts["queries"] >= 10000:
                raise Budget()
            counts["queries"] += 1
            if "FOR UPDATE" in str(args[0]).upper():
                raise AssertionError("Read-only profiling attempted a row lock")
            return sql(*args, **kwargs)
        def counter(function, key):
            def wrapped(*args, **kwargs):
                counts[key] += 1
                return function(*args, **kwargs)
            return wrapped
        status = "completed"
        try:
            with patch.object(frappe.db, "sql", query), patch.object(provenance, "source_plan", counter(provenance.source_plan, "plan_calls")), patch.object(provenance, "authorize", counter(provenance.authorize, "authorize_calls")), patch.object(output_sources, "binding_plan", counter(output_sources.binding_plan, "binding_plan_calls")), patch.object(output_sources, "authorize_binding", counter(output_sources.authorize_binding, "binding_authorize_calls")):
                effect()
        except Budget:
            status = "bounded-profile-budget-reached"
        finally:
            frappe.db.rollback()
        phases.append({"phase": name, "status": status, "elapsed_seconds": round(time.monotonic() - start, 4), **counts})
    try:
        frappe.set_user(fixture["users"]["author"]["user"])
        actor = current_actor()
        with scopes.activate("Company", company, None):
            phase("complete_plan_discovery", lambda: lockplan.revision_plan(company, actor, request["subject_id"], current_bindings=True, lock=False))
            generated = next(row["result"]["measurement"]["source"]["revision_id"] for row in checkpoint["recovered"] if "measurement" in row["result"])
            phase("one_generated_citation_original_source_authorization", lambda: docs.get_company_citation(company, generated, 1, actor=actor))
            phase("current_acceptance_manifest_rebuild", lambda: governance.approval_manifest(actor=actor, company=company, project=None, subject_id=request["subject_id"], expected_version=request["expected_version"], lock=False, scope_type="Company"))
        result = {"status": "profile-recorded", "company": company, "qualification": "Bounded native read-only elapsed/query counters; no row locks, mutations, caches or performance success claimed", "phase_budget_seconds": phase_budget_seconds, "phases": phases, "live_model_qualified": False}
        path = _save("est-generated-profile-" + uuid4().hex + ".json", result)
        return {**result, "private_result": path}
    finally:
        frappe.db.rollback()
        frappe.set_user("Administrator")


def prepare_generated_identities(private_fixture):
    """ROOT-SERIAL-SLOT ONLY: distinct canonical people for isolated long proofs.

    Existing authored records/receipts retain their original owners. This creates
    new native fixture identities/roles; it never resets an existing identity.
    """
    import secrets
    import frappe
    from frappe.permissions import add_permission, update_permission_property
    from cipher_aec.install import _person, _user, _binding, _grant_company
    from cipher_aec.governance.context import COMPANY_ABILITIES, trusted_write
    fixture = _load(private_fixture)
    marker = uuid4().hex[:12]
    people = {"author": "EST-GENERATED-AUTHOR-" + marker, "reviewer": "EST-GENERATED-REVIEWER-" + marker}
    roles = {key: "EST generated native " + key + " " + marker for key in ("author", "reviewer")}
    replacement = deepcopy(fixture)
    with trusted_write():
        for key, role in roles.items():
            frappe.get_doc({"doctype": "Role", "role_name": role}).insert(ignore_permissions=True)
            for doctype in ("Company", "Customer", "Supplier", "Item", "UOM", "Currency", "Price List", "Account", "Opportunity", "Quotation"):
                add_permission(doctype, role, 0)
                for permission in ("read", "select"):
                    update_permission_property(doctype, role, 0, permission, 1)
                if key == "author" and doctype in ("Opportunity", "Quotation"):
                    for permission in ("create", "write"):
                        update_permission_property(doctype, role, 0, permission, 1)
        for key in ("author", "alias", "reviewer"):
            person = people["author" if key == "alias" else key]
            _person(person, "Explicit independent generated-source fixture " + key)
            user = "est.generated." + key + "." + marker + "@cipher.example"
            password = secrets.token_urlsafe(32)
            _user(user, "Explicit generated-source " + key, password)
            _binding(user, person)
            doc = frappe.get_doc("User", user)
            doc.append("roles", {"role": roles["reviewer" if key == "reviewer" else "author"]})
            doc.save(ignore_permissions=True)
            replacement["users"][key] = {"user": user, "person": person, "password": password}
        for ability in sorted(COMPANY_ABILITIES):
            _grant_company(people["author"], fixture["company"], ability)
        for ability in ("company.read", "commercial.read", "document.read", "estimate.read", "approval.decide"):
            _grant_company(people["reviewer"], fixture["company"], ability)
    replacement.update(native_role=roles["author"], reviewer_native_role=roles["reviewer"], identity_marker=marker,
        previous_identity_fixture=private_fixture, original_authored_records_untouched=True)
    path = _save("est-generated-" + marker + ".secret.json", replacement)
    frappe.db.commit()
    return {"private_fixture": path, "company": fixture["company"], "distinct_author_reviewer_canonical_people": True,
        "original_record_owners_and_receipts_untouched": True, "existing_credentials_reset": False,
        "dedicated_native_roles": roles}


def set_generated_unit_visibility(private_fixture, restricted):
    """Only new fixture reviewer: precise native UOM permissions, reversible.

    Never edit shared native master/Role/DocPerm rows. Unsupported native User
    Permission behavior fails the fixture before committing or claiming proof.
    """
    import frappe
    fixture = _load(private_fixture)
    if type(restricted) is not bool or not fixture.get("identity_marker"):
        raise RuntimeError("A separate root-provisioned identity fixture is required")
    reviewer = fixture["users"]["reviewer"]["user"]
    if not reviewer.startswith("est.generated.reviewer."):
        raise RuntimeError("Only the new isolated reviewer may be restricted")
    marker = fixture["identity_marker"]
    path = Path(frappe.get_site_path("private", "cipher-fixtures", "est-generated-unit-permissions-" + marker + ".json"))
    allowed = {fixture["native_units"][key] for key in ("sf", "sy", "ft")}
    if restricted:
        if frappe.db.exists("User Permission", {"user": reviewer, "allow": "UOM"}):
            raise RuntimeError("Refusing an existing native permission inventory")
        if path.exists():
            previous = json.loads(path.read_text())
            if (previous["reviewer"] != reviewer or previous["company"] != fixture["company"]
                    or set(previous["allowed"]) != allowed or any(frappe.db.exists("User Permission", name) for name in previous["rows"])):
                raise RuntimeError("The previous native restriction is not independently restored")
            path.rename(path.with_name(path.stem + "-restored-" + uuid4().hex + ".json"))
        rows = []
        try:
            for name in sorted(allowed):
                rows.append(frappe.get_doc({"doctype": "User Permission", "user": reviewer, "allow": "UOM", "for_value": name, "apply_to_all_doctypes": 1}).insert(ignore_permissions=True).name)
            frappe.clear_cache(user=reviewer)
            assert frappe.has_permission("UOM", ptype="read", doc=frappe.get_doc("UOM", fixture["native_units"]["sf"]), user=reviewer)
            assert not frappe.has_permission("UOM", ptype="read", doc=frappe.get_doc("UOM", fixture["native_units"]["count"]), user=reviewer)
            assert frappe.has_permission("Company", ptype="read", doc=frappe.get_doc("Company", fixture["company"]), user=reviewer)
            _save(path.name, {"reviewer": reviewer, "company": fixture["company"], "rows": rows, "allowed": sorted(allowed)})
            frappe.db.commit()
        except BaseException:
            frappe.db.rollback()
            frappe.clear_cache(user=reviewer)
            raise
    else:
        stored = json.loads(path.read_text())
        if stored["reviewer"] != reviewer or stored["company"] != fixture["company"] or set(stored["allowed"]) != allowed:
            raise RuntimeError("Native permission restore scope mismatch")
        for name in stored["rows"]:
            row = frappe.get_doc("User Permission", name)
            if row.user != reviewer or row.allow != "UOM" or row.for_value not in allowed:
                raise RuntimeError("Refusing another native permission row")
            frappe.delete_doc("User Permission", name, ignore_permissions=True)
        frappe.db.commit()
        frappe.clear_cache(user=reviewer)
        assert not frappe.db.exists("User Permission", {"user": reviewer, "allow": "UOM"})
        assert frappe.has_permission("UOM", ptype="read", doc=frappe.get_doc("UOM", fixture["native_units"]["count"]), user=reviewer)
    return {"restricted": restricted, "reviewer_outer_area_unit_read_retained": True, "producer_only_count_unit_read": not restricted, "shared_roles_and_masters_changed": False, "company_a_state_changed": False}


def continue_generated_union_acceptance(private_fixture, private_dag):
    """Continue committed new-person grant; do not recreate prior commands."""
    import os
    from contextlib import contextmanager
    from unittest.mock import patch
    import frappe
    from cipher_aec.api.contracts import digest
    from cipher_aec.estimating import sources, lockplan, units
    from cipher_aec.commercial import native
    from cipher_aec.documents import provenance
    fixture = _load(private_fixture); company = fixture["company"]
    dag = json.loads(Path(private_dag).read_text()); assert dag["company"] == company
    base = Path(frappe.get_site_path("private", "cipher-fixtures"))
    # Select the exact latest failed recorder run for these new actors only.
    candidates = []
    for path in base.glob("est-generated-journal-*"):
        entries = [json.loads(line) for line in path.read_text().splitlines()]
        if not entries: continue
        name = digest({"person": fixture["users"]["author"]["person"], "operation_id": entries[0]["payload"]["operation_id"]})
        if frappe.db.exists("Cipher Command Receipt", name): candidates.append((path.stat().st_mtime, path, entries))
    _, prior_journal, entries = max(candidates)
    recovered = []
    for entry in entries:
        role = "reviewer" if entry["method"].endswith("decide_packet") else "author"
        name = digest({"person": fixture["users"][role]["person"], "operation_id": entry["payload"]["operation_id"]})
        row = frappe.db.get_value("Cipher Command Receipt", name, ["result_json", "result_hash"], as_dict=True)
        if row:
            result = json.loads(row.result_json); assert digest(result) == row.result_hash
            recovered.append({"entry": entry, "result": result})
    values = {}
    for row in recovered:
        if ".estimating." in row["entry"]["method"]:
            for key in ("revision", "calculation", "rate_source", "conversion"):
                if key in row["result"]: values[key] = row["result"][key]
        for key in ("calibration", "measurement", "binding"):
            if key in row["result"]: values[key] = row["result"][key]
        packet = row["result"].get("packet")
        if packet and packet["action"] == "estimate.accept.v1": values["packet"] = packet
    assert values["packet"]["state"] == "Granted"
    rpc = _timed_rpc(fixture); trace, acquisitions, new_operations = [], [], []
    actual_prepared, actual_unit, actual_native = lockplan.prepared, units.qualified, native.require_native
    def unit(name, **kwargs):
        if kwargs.get("lock"):trace.append(("UOM", name))
        return actual_unit(name, **kwargs)
    def master(kind, name, actor, **kwargs):
        if kwargs.get("lock") and kind != "UOM":trace.append((kind, name))
        return actual_native(kind, name, actor, **kwargs)
    @contextmanager
    def prepared(plan, actor, company, **kwargs):
        root = not lockplan.active_for(actor, company) and not provenance.has_prelocked(); start = len(trace)
        with actual_prepared(plan, actor, company, **kwargs) as held:
            if root:
                expected = [("UOM", x) for x in held["unit_ids"]] + [("Currency", x) for x in held["currencies"]] + [(x["doctype"], x["name"]) for x in held["native_refs"]]
                assert trace[start:] == expected
                acquisitions.append({"plan": held, "actual_native_lock_calls": trace[start:]})
            yield held
    journal = base / ("est-generated-continuation-" + uuid4().hex + ".jsonl")
    fd = os.open(journal, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
    def command(method, payload):
        args = {"company": company, "operation_id": str(uuid4()), **payload}
        entry = {"method": method, "role": rpc.role, "payload": deepcopy(args)}
        new_operations.append(entry); os.write(fd, (json.dumps(entry) + "\n").encode()); os.fsync(fd)
        return args, rpc.invoke(method, args)
    try:
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True), patch.object(lockplan, "prepared", prepared), patch.object(units, "qualified", unit), patch.object(native, "require_native", master):
            rpc.login("author")
            node = dag["nodes"][0]
            command("cipher_aec.commercial.api.save_proposal_revision", {"proposal_id": node["proposal"]["id"], "expected_revision": node["proposal"]["revision_number"], "expected_native_fingerprint": node["revision"]["native_fingerprint"], "composition": node["revision"]["composition"]})
            packet = values["packet"]
            execute_args, accepted = command("cipher_aec.api.company_approvals.execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]})
            baseline = accepted["effect"]["acceptance"]
            # Shared engine rebuilds and requires EXACT manifest equality before
            # consumption. Successful consume after the producer-only successor
            # therefore proves the selected immutable facts were unchanged.
            assert baseline["manifest"] == packet["review_manifest"]
            facts = baseline["manifest"]["effect"]["facts"]
            assert len(facts["generated_sources"]) == 3
            assert baseline["total"] == {"amount": "250.00", "currency": "EUR"}
            rpc.login("alias")
            for suffix, key in (("calculate_revision", "revision"), ("create_measurement", "measurement")):
                entry = next(row["entry"] for row in recovered if row["entry"]["method"].endswith(suffix))
                replay = rpc.invoke(entry["method"], entry["payload"])
                assert replay["operation"]["replayed"] and replay[key] == values[key]
            replay = rpc.invoke("cipher_aec.api.company_approvals.execute_packet", execute_args)
            assert replay["operation"]["replayed"] and replay["effect"]["acceptance"] == baseline
            assert frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": values["revision"]["id"]}) == 1
        result = {"status": "passed", "company": company, "qualification": "Actual native Frappe/ERPNext/MariaDB with distinct synthetic Session people; not HTTP or enterprise performance qualification",
            "revision": values["revision"], "calculation": values["calculation"], "rate": values["rate_source"], "conversion": values["conversion"], "calibration": values["calibration"], "measurement": values["measurement"], "binding": values["binding"], "packet": packet, "acceptance": baseline,
            "producer_dag": dag["nodes"], "producer_only_native_quotation_successor_keeps_exact_pending_manifest": True,
            "producer_unit_absent_outer_snapshot": fixture["qualified_unit"]["id"], "producer_currency_absent_outer_snapshot": "USD",
            "lock_acquisitions": acquisitions, "command_timings": rpc.timings, "timing_journal_path": rpc.timing_path,
            "prior_journal": str(prior_journal), "continuation_journal": str(journal), "operations": [row["entry"] for row in recovered] + new_operations,
            "canonical_successful_receipt_replays": 3, "same_uuid_conflict_recovery_claimed": False,
            "interrupted_old_actor_operation_separate": True, "live_model_qualified": False, "external_provider_qualified": False}
        path = _save("est-generated-union-qualified-" + uuid4().hex + ".json", result)
        return {"status": "passed", "private_result": path, "total": baseline["total"], "generated_nodes": 3, "timings": rpc.timings, "live_model_qualified": False}
    finally:
        os.close(fd); rpc.close()


def run_generated_memo_delta(private_fixture, private_union):
    """Equivalent selected inputs under one profiled logical-command lifetime."""
    import os
    import frappe
    from unittest.mock import patch
    from cipher_aec.api.contracts import digest
    from cipher_aec.estimating import sources
    fixture = _load(private_fixture); prior = json.loads(Path(private_union).read_text())
    company = fixture["company"]; assert prior["company"] == company
    rpc = _timed_rpc(fixture)
    path = Path(frappe.get_site_path("private", "cipher-fixtures", "est-generated-memo-journal-" + uuid4().hex + ".jsonl"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
    operations = []
    def command(method, values):
        args = {"company": company, "operation_id": str(uuid4()), **values}
        entry = {"method": method, "role": rpc.role, "payload": deepcopy(args)}
        operations.append(entry); os.write(fd, (json.dumps(entry) + "\n").encode()); os.fsync(fd)
        return args, rpc.invoke(method, args)
    est, take, gov = "cipher_aec.estimating.company_api.", "cipher_aec.takeoff.company_api.", "cipher_aec.api.company_approvals."
    try:
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True):
            rpc.login("author")
            _, made = command(est + "create_estimate", {"title": "Equivalent immutable input memo comparison " + uuid4().hex[:8], "currency": prior["revision"]["currency"], "pricing_date": prior["revision"]["pricing_date"], "pursuit_id": prior["acceptance"]["manifest"]["effect"]["facts"]["pursuit"]["pursuit_id"]})
            inputs = prior["calculation"]["inputs"]
            calc_args, calculated = command(est + "calculate_revision", {"estimate_id": made["estimate"]["id"], "expected_revision": None, "lines": inputs["lines"], "adjustments": inputs["adjustments"], "conversion_ids": [row["id"] for row in inputs["unit_manifest"]["unit_conversions"]], "basis_description": inputs["basis_description"], "basis_citations": [{key: cite[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")} for cite in inputs["basis_citations"]]})
            assert calculated["revision"]["total"] == prior["revision"]["total"]
            command(take + "bind_line", {"measurement_id": prior["measurement"]["id"], "estimate_line_record": calculated["revision"]["line_record_ids"][0], "quantity_basis": "net-quantity-v1", "reason": "Same selected source/measurement inputs; operation lifetime profiling only"})
            _, requested = command(gov + "request_action", {"action": "estimate.accept.v1", "subject_id": calculated["revision"]["id"], "expected_version": digest(calculated["revision"])})
            packet = requested["packet"]
            rpc.login("reviewer")
            command(gov + "decide_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Independent exact original sources/current geometry review"})
            rpc.login("author")
            execute_args, accepted = command(gov + "execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]})
            baseline = accepted["effect"]["acceptance"]
            # The command has committed. Preserve its exact authority/UUID and
            # observations before any recorder assertion, so a metrics failure
            # never requires creating a second business effect to investigate.
            observation = _save("est-generated-memo-observed-" + uuid4().hex + ".json", {
                "status": "committed-consumption-observed-not-yet-qualified",
                "company": company, "baseline": baseline, "calculated": calculated,
                "packet": packet, "operations": operations,
                "command_timings": rpc.timings, "operation_journal": str(path),
                "timing_journal_path": rpc.timing_path,
                "source_snapshot_start": rpc.source_snapshot,
                "source_snapshot_at_consumption": _source_snapshot(),
                "live_model_qualified": False, "external_provider_qualified": False})
            assert baseline["manifest"] == packet["review_manifest"]
            assert baseline["manifest"]["effect"]["facts"]["generated_sources"] == prior["acceptance"]["manifest"]["effect"]["facts"]["generated_sources"]
            consumption = rpc.timings[-1]
            assert rpc.source_snapshot == _source_snapshot(), "Source generation changed during native proof"
            assert consumption["logical_operation_counters"], "Shared Company command hook was not captured"
            counters = consumption["logical_operation_counters"][-1]
            assert counters["producer_hits"] > 0 and counters["producer_authorized"] == 6, counters
            assert counters["prelocked_scopes"] > 1
            assert consumption["successful_exact_byte_integrity_checks"] == consumption["actual_artifact_disk_reads"] > 0
            rpc.login("alias")
            replay = rpc.invoke(gov + "execute_packet", execute_args)
            assert replay["operation"]["replayed"] and replay["effect"]["acceptance"] == baseline
            result = {"status": "passed", "company": company, "qualification": "Bounded real Frappe/ERPNext/MariaDB fixture timings, not HTTP or enterprise performance qualification", "same_selected_immutable_pricing_and_geometry_inputs": True,
                "old_baseline_id": prior["acceptance"]["id"], "new_baseline_id": baseline["id"], "exact_source_node_manifest_unchanged": True,
                "author_and_reviewer_original_authority_evaluations": counters["producer_authorized"], "memo_counters": counters,
                "source_snapshot_start": rpc.source_snapshot, "source_snapshot_end": _source_snapshot(),
                "committed_observation": observation,
                "command_timings": rpc.timings, "timing_journal_path": rpc.timing_path, "operation_journal": str(path), "operations": operations,
                "baseline": baseline, "calculated": calculated, "packet": packet, "live_model_qualified": False, "external_provider_qualified": False}
            target = _save("est-generated-memo-qualified-" + uuid4().hex + ".json", result)
            return {"status": "passed", "private_result": target, "consumption": consumption, "live_model_qualified": False}
    finally:
        os.close(fd); rpc.close()


def run_generated_producer_unit_denial(private_fixture, private_union, private_memo):
    """Producer-only native UOM rights remain current across logical commands."""
    import os
    import frappe
    from unittest.mock import patch
    from cipher_aec.api.contracts import digest
    from cipher_aec.estimating import sources
    fixture = _load(private_fixture)
    union, memo = [json.loads(Path(name).read_text()) for name in (private_union, private_memo)]
    company = fixture["company"]
    assert union["company"] == memo["company"] == company
    rpc = _timed_rpc(fixture)
    path = Path(frappe.get_site_path("private", "cipher-fixtures", "est-generated-unit-denial-journal-" + uuid4().hex + ".jsonl"))
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
    operations = []
    def command(method, values, expected_codes=()):
        args = {"company": company, "operation_id": str(uuid4()), **values}
        operations.append({"method": method, "role": rpc.role, "payload": deepcopy(args)})
        os.write(fd, (json.dumps(operations[-1]) + "\n").encode()); os.fsync(fd)
        return args, rpc.invoke(method, args, expected_codes=expected_codes)
    est, take, gov = "cipher_aec.estimating.company_api.", "cipher_aec.takeoff.company_api.", "cipher_aec.api.company_approvals."
    restricted = False
    try:
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True):
            rpc.login("author")
            inputs = memo["calculated"]["calculation"]["inputs"]
            _, successor = command(est + "calculate_revision", {"estimate_id": memo["calculated"]["revision"]["estimate"], "expected_revision": memo["calculated"]["revision"]["id"],
                "lines": inputs["lines"], "adjustments": inputs["adjustments"], "conversion_ids": [row["id"] for row in inputs["unit_manifest"]["unit_conversions"]],
                "basis_description": inputs["basis_description"], "basis_citations": [{key: cite[key] for key in ("revision_id", "page", "excerpt_sha256", "source_sha256")} for cite in inputs["basis_citations"]]})
            command(take + "bind_line", {"measurement_id": union["measurement"]["id"], "estimate_line_record": successor["revision"]["line_record_ids"][0], "quantity_basis": "net-quantity-v1", "reason": "Producer-only UOM permission revocation qualification"})
            _, requested = command(gov + "request_action", {"action": "estimate.accept.v1", "subject_id": successor["revision"]["id"], "expected_version": digest(successor["revision"])})
            packet = requested["packet"]
            rpc.login("reviewer")
            decide_args, _ = command(gov + "decide_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "decision": "Grant", "reason": "Exact producer-only native rights are currently available"})
            before_rights = _source_snapshot()
            frappe.set_user("Administrator")
            isolated_rights = set_generated_unit_visibility(private_fixture, True); restricted = True
            rpc.login("reviewer")
            denied = {"not_found"}
            probes = [
                ("cipher_aec.documents.company_api.get_citation", {"revision_id": union["producer_dag"][-1]["prepared"]["revision_id"], "page": 1}),
                (est + "get_record", {"kind": "rate", "record_id": union["rate"]["id"]}),
                (est + "get_record", {"kind": "acceptance", "record_id": memo["baseline"]["id"]}),
                (take + "get_record", {"kind": "measurement", "record_id": union["measurement"]["id"]}),
                (gov + "read_packet", {"packet_id": memo["packet"]["id"]}),
                (gov + "decide_packet", decide_args),
                ("cipher_aec.api.company.operation", {"operation_id": decide_args["operation_id"]}),
            ]
            for method, body in probes:
                rpc.invoke(method, {"company": company, **body}, expected_codes=denied)
            rpc.login("author")
            assert rpc.invoke(est + "get_record", {"company": company, "kind": "acceptance", "record_id": memo["baseline"]["id"]}) == memo["baseline"]
            execute_args, _ = command(gov + "execute_packet", {"packet_id": packet["id"], "manifest_hash": packet["manifest_hash"]}, expected_codes={"reviewer_authority_revoked"})
            assert not frappe.db.exists("Cipher Estimate Acceptance", {"estimate_revision": successor["revision"]["id"]})
            frappe.set_user("Administrator")
            restored_rights = set_generated_unit_visibility(private_fixture, False); restricted = False
            rpc.login("author")
            completed = rpc.invoke(gov + "execute_packet", execute_args)
            replay = rpc.invoke(gov + "execute_packet", execute_args)
            assert replay["operation"]["replayed"] and replay["effect"] == completed["effect"]
            assert frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": successor["revision"]["id"]}) == 1
            rpc.login("reviewer")
            assert rpc.invoke(gov + "decide_packet", decide_args)["operation"]["replayed"]
            assert before_rights == _source_snapshot() == rpc.source_snapshot
            result = {"status": "passed", "company": company, "qualification": "Actual native Frappe/ERPNext/MariaDB, synthetic Sessions; not HTTP or enterprise performance qualification",
                "isolated_native_permission": isolated_rights, "restored_native_permission": restored_rights,
                "producer_only_count_denied_outer_area_allowed": True, "executor_retains_source_access": True,
                "denied_original_generated_record_baseline_packet_and_reviewers_own_receipts": True,
                "new_effect_refused_for_revoked_reviewer": True, "same_persisted_execute_uuid_after_restoration": execute_args["operation_id"],
                "one_effect_then_same_uuid_replay": True, "source_snapshot_start": rpc.source_snapshot, "source_snapshot_end": _source_snapshot(),
                "operations": operations, "operation_journal": str(path), "calls": rpc.calls, "command_timings": rpc.timings,
                "live_model_qualified": False, "external_provider_qualified": False}
            artifact = _save("est-generated-unit-denial-qualified-" + uuid4().hex + ".json", result)
            return {"status": "passed", "private_result": artifact, "native_permission_restored": True}
    finally:
        if restricted:
            frappe.set_user("Administrator")
            set_generated_unit_visibility(private_fixture, False)
        os.close(fd); rpc.close()


def continue_generated_producer_unit_denial(private_fixture, private_memo, private_journal):
    """Finish the committed original grant after the positive-read budget stop.

    No replacement revision, packet or review is authored. The first execute
    UUID is persisted before its first send and reused after rights restoration.
    """
    import frappe
    from unittest.mock import patch
    from cipher_aec.api.contracts import digest
    from cipher_aec.estimating import sources
    fixture = _load(private_fixture)
    company = fixture["company"]
    memo = json.loads(Path(private_memo).read_text())
    journal_path = Path(private_journal).resolve()
    base = Path(frappe.get_site_path("private", "cipher-fixtures")).resolve()
    if not journal_path.is_relative_to(base) or not journal_path.name.startswith("est-generated-unit-denial-journal-"):
        raise RuntimeError("Use the exact preserved generated-source rights journal")
    entries = [json.loads(value) for value in journal_path.read_text().splitlines()]
    recovered = []
    for entry in entries:
        assert entry["payload"]["company"] == company
        person = fixture["users"][entry["role"]]["person"]
        name = digest({"person": person, "operation_id": entry["payload"]["operation_id"]})
        row = frappe.db.get_value("Cipher Command Receipt", name, ["result_json", "result_hash"], as_dict=True)
        assert row is not None
        result = json.loads(row.result_json); assert digest(result) == row.result_hash
        recovered.append((entry, result))
    requested = next(result for entry, result in recovered if entry["method"].endswith("request_action"))
    packet = requested["packet"]
    decide_entry = next(entry for entry, _ in recovered if entry["method"].endswith("decide_packet"))
    assert decide_entry["payload"]["packet_id"] == packet["id"]
    revision = next(result["revision"] for entry, result in recovered if entry["method"].endswith("calculate_revision"))
    assert not frappe.db.exists("Cipher Estimate Acceptance", {"estimate_revision": revision["id"]})
    assert not frappe.db.exists("Cipher Approval Consumption", {"packet": packet["id"]})
    execute_args = {"company": company, "packet_id": packet["id"], "manifest_hash": packet["manifest_hash"], "operation_id": str(uuid4())}
    intent = _save("est-generated-unit-denial-execute-intent-" + uuid4().hex + ".json", {
        "company": company, "original_journal": str(journal_path), "original_request_uuid": next(entry["payload"]["operation_id"] for entry, _ in recovered if entry["method"].endswith("request_action")),
        "original_decide_uuid": decide_entry["payload"]["operation_id"], "method": "cipher_aec.api.company_approvals.execute_packet", "payload": execute_args,
        "qualification": "Original grant retained; this execute UUID is recorded before its first send"})
    rpc = _timed_rpc(fixture)
    est, gov = "cipher_aec.estimating.company_api.", "cipher_aec.api.company_approvals."
    restricted = False
    try:
        with patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True):
            rpc.login("author")
            original = rpc.invoke(est + "get_record", {"company": company, "kind": "acceptance", "record_id": memo["baseline"]["id"]})
            assert original == memo["baseline"]
            positive_read = rpc.timings[-1]
            frappe.set_user("Administrator")
            denied_rights = set_generated_unit_visibility(private_fixture, True); restricted = True
            rpc.login("reviewer")
            # The explicit read graph and the prior command memo cannot carry
            # authority across the independently committed native revocation.
            rpc.invoke(est + "get_record", {"company": company, "kind": "acceptance", "record_id": original["id"]}, expected_codes={"not_found"})
            rpc.invoke(gov + "decide_packet", decide_entry["payload"], expected_codes={"not_found"})
            rpc.login("author")
            rpc.invoke(gov + "execute_packet", execute_args, expected_codes={"reviewer_authority_revoked"})
            assert not frappe.db.exists("Cipher Estimate Acceptance", {"estimate_revision": revision["id"]})
            assert not frappe.db.exists("Cipher Approval Consumption", {"packet": packet["id"]})
            frappe.set_user("Administrator")
            restored_rights = set_generated_unit_visibility(private_fixture, False); restricted = False
            rpc.login("author")
            completed = rpc.invoke(gov + "execute_packet", execute_args)
            baseline = completed["effect"]["acceptance"]
            consume_timing = deepcopy(rpc.timings[-1])
            observation = _save("est-generated-unit-denial-consumed-" + uuid4().hex + ".json", {
                "status": "committed-effect-observed-not-yet-qualified", "company": company,
                "execute_args": execute_args, "intent": intent, "completed": completed,
                "command_timings": rpc.timings, "source_snapshot": rpc.source_snapshot})
            assert baseline["manifest"] == packet["review_manifest"]
            replay = rpc.invoke(gov + "execute_packet", execute_args)
            assert replay["operation"]["replayed"] and replay["effect"] == completed["effect"]
            rpc.login("reviewer")
            assert rpc.invoke(gov + "decide_packet", decide_entry["payload"])["operation"]["replayed"]
            assert frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": revision["id"]}) == 1
            assert frappe.db.count("Cipher Approval Consumption", {"packet": packet["id"]}) == 1
            assert rpc.source_snapshot == _source_snapshot()
            result = {"status": "passed", "company": company, "qualification": "Actual native Frappe/ERPNext/MariaDB with explicit synthetic Sessions, not HTTP or workload/p95 performance qualification",
                "original_grant_and_review_receipts_reused": True, "prior_seven_denial_probes_preserved_separately": True,
                "positive_original_baseline_read": positive_read, "native_isolation": denied_rights, "restoration": restored_rights,
                "new_read_graph_and_completed_command_memo_do_not_survive_native_revocation": True,
                "pending_consume_refused_for_reviewer_native_rights": True, "same_persisted_execute_uuid_after_restoration": execute_args["operation_id"],
                "one_acceptance_one_consumption_then_exact_receipt_replay": True, "baseline": baseline,
                "intent": intent, "committed_observation": observation, "original_journal": str(journal_path),
                "calls": rpc.calls, "command_timings": rpc.timings, "timing_journal_path": rpc.timing_path,
                "source_snapshot_start": rpc.source_snapshot, "source_snapshot_end": _source_snapshot(),
                "live_model_qualified": False, "external_provider_qualified": False}
            path = _save("est-generated-unit-denial-continuation-" + uuid4().hex + ".json", result)
            return {"status": "passed", "private_result": path, "native_permission_restored": True,
                "positive_original_baseline_read": positive_read, "consume": consume_timing}
    finally:
        if restricted:
            frappe.set_user("Administrator")
            set_generated_unit_visibility(private_fixture, False)
        rpc.close()


def profile_generated_recorded_authority(private_fixture, private_continuation):
    """Exact successful replay and separate bounded nonlocking fact attribution.

    Neither phase creates or measures a new acceptance effect. The second phase
    has no source graph admission/memo and refuses all FOR UPDATE statements.
    """
    import frappe
    from unittest.mock import patch
    from cipher_aec.api.contracts import digest
    from cipher_aec.api.errors import DomainError
    from cipher_aec.estimating import governance, scopes, sources
    from cipher_aec.governance.context import current_actor
    fixture = _load(private_fixture); prior = _load(private_continuation)
    company = fixture["company"]; assert prior["company"] == company
    intent = json.loads(Path(prior["intent"]).read_text())
    args = intent["payload"]; assert args["company"] == company
    name = digest({"person": fixture["users"]["author"]["person"], "operation_id": args["operation_id"]})
    record = frappe.db.get_value("Cipher Command Receipt", name, ["command", "result_json", "result_hash"], as_dict=True)
    assert record and record.command == "approval.execute"
    stored = json.loads(record.result_json)
    assert digest(stored) == record.result_hash and stored["effect"]["acceptance"] == prior["baseline"]
    before = frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": prior["baseline"]["estimate_revision"]})
    rpc = _timed_rpc(fixture, phase_profile=True)
    fixture_gate = patch.object(sources, "GENERATED_INPUTS_QUALIFIED", True)
    fixture_gate.start()
    try:
        rpc.login("author")
        replay = rpc.invoke("cipher_aec.api.company_approvals.execute_packet", args)
        assert replay["operation"]["replayed"] and replay["effect"] == stored["effect"]
        actor = current_actor()
        read_status = "completed"
        try:
            with scopes.activate("Company", company, None):
                rpc.observe_read("direct-domain-profile.estimate._facts.lockFalse", lambda: governance._facts(
                    actor=actor, company=company, project=None, subject_id=prior["baseline"]["estimate_revision"], lock=False))
        except DomainError as error:
            if error.code != "fixture_profile_budget":
                raise
            read_status = "fixed-eight-second-ten-thousand-query-profile-cap"
        finally:
            frappe.db.rollback()
        assert frappe.db.count("Cipher Estimate Acceptance", {"estimate_revision": prior["baseline"]["estimate_revision"]}) == before == 1
        assert rpc.source_snapshot == _source_snapshot()
        result = {"status": "attribution-recorded", "company": company,
            "qualification": "Known successful exact-UUID locked receipt replay plus a separate direct lock=False current-facts profile; neither measures a fresh consume. Synthetic native Sessions, not HTTP.",
            "new_acceptance_intent_or_effect_created": False, "existing_execute_uuid": args["operation_id"], "current_facts_read_status": read_status,
            "inclusive_phase_counts_may_overlap": True, "elapsed_includes_fixture_profiling_overhead": True,
            "command_and_read_profiles": rpc.timings, "source_snapshot_start": rpc.source_snapshot, "source_snapshot_end": _source_snapshot(),
            "timing_journal_path": rpc.timing_path, "live_model_qualified": False, "external_provider_qualified": False}
        path = _save("est-generated-authority-attribution-" + uuid4().hex + ".json", result)
        return {"status": result["status"], "private_result": path, "profiles": rpc.timings}
    finally:
        fixture_gate.stop()
        rpc.close()
