"""The Cipher service façade used by the console, the CLI and the tests.

One instance owns one SQLite workspace.  Every consequential change follows
the same shape:

    request_approval(operation, subject)  -> pending approval with a bound manifest
    approve(approval_id, approver)        -> human grants it
    execute(approval_id)                  -> manifest is rebuilt from current state,
                                             consumed atomically, and the action applied
                                             as an idempotent command
"""
from __future__ import annotations

import importlib
import os
import tempfile
from typing import Any

from .core.approvals import ApprovalError, ApprovalExpired, Approvals, StaleApprovalError, material_hash
from .core.db import register_schema_version

# Configured v2 modules are required: a missing or broken module aborts startup.
# Each module must expose:
#   SCHEMA_NAME: str, SCHEMA_STATEMENTS: list[str]   -> registered as the next schema version, in this order
#   PLUGIN_NAME: str                                   -> the operation prefix it owns, e.g. "asset" for "asset.*"
#   class Plugin: __init__(self, cipher); manifest_for(operation, subject_id, *, actor_role) -> manifest;
#                 apply(operation, subject_id, *, approval_id, manifest, actor, period_id) -> dict;
#                 state(project_id) -> dict
PLUGIN_MODULES = [
    "apps.cipher.domain.assets",
    "apps.cipher.domain.schedule",
    "apps.cipher.domain.drawings",
    "apps.cipher.domain.reimbursements",
    "apps.cipher.domain.banking",
    "apps.cipher.domain.labor",
    "apps.cipher.domain.procurement",
    "apps.cipher.domain.field",
    "apps.cipher.domain.close",
    "apps.cipher.domain.handoff",
    "apps.cipher.domain.rights",
    "apps.cipher.domain.ap_intake",
    # governors (GOVERNOR = True): policy over approvals other modules own
    "apps.cipher.domain.people",
    "apps.cipher.domain.payment_policy",
    "apps.cipher.domain.contracts",
    "apps.cipher.domain.accounting",  # required; schema registers after every historical entry
]
# Optional plugin hook used by the close module's checklist:
#   close_checks(period_id) -> list[{"check": str, "ok": bool, "detail": str}]
_LOADED_PLUGIN_MODULES: list[Any] = []
_LATE_ACCOUNTING_MODULE = "apps.cipher.domain.accounting"
_LATE_ACCOUNTING_SCHEMA = "accounting_practice_delivery"


class PluginLoadError(RuntimeError):
    """A configured module could not supply its schema or controls."""


def _load_plugin_modules() -> list[Any]:
    global _LOADED_PLUGIN_MODULES
    if _LOADED_PLUGIN_MODULES:
        return _LOADED_PLUGIN_MODULES
    loaded: list[Any] = []
    plugin_names = {"core_reconciliation", "ricky_sdk"}
    for name in PLUGIN_MODULES:
        from .core import db as schema_registry
        late_accounting = name == _LATE_ACCOUNTING_MODULE
        catalog_before = tuple((version, schema, tuple(sql)) for version, schema, sql in schema_registry.SCHEMA_CATALOG) if late_accounting else None
        try:
            mod = importlib.import_module(name)
            if late_accounting and tuple((version, schema, tuple(sql)) for version, schema, sql in schema_registry.SCHEMA_CATALOG) != catalog_before:
                raise ValueError("accounting import must not register or change schema entries")
        except Exception as exc:
            raise PluginLoadError(f"configured plugin {name} failed to import: {exc}") from exc
        try:
            schema_name = mod.SCHEMA_NAME
            statements = mod.SCHEMA_STATEMENTS
            if not isinstance(schema_name, str) or not schema_name.strip():
                raise ValueError("SCHEMA_NAME must be a nonempty string")
            if not isinstance(statements, list) or any(not isinstance(s, str) or not s.strip() for s in statements):
                raise ValueError("SCHEMA_STATEMENTS must be a list of nonempty strings")
            if late_accounting:
                if schema_name != _LATE_ACCOUNTING_SCHEMA or not statements:
                    raise ValueError("accounting must supply its full named schema")
                if getattr(mod, "DEFER_SCHEMA_REGISTRATION", None) is not True:
                    raise ValueError("accounting must declare its explicit late registration")
                if not callable(getattr(mod, "register_accounting_schema", None)):
                    raise ValueError("accounting must supply its named late registrar")
            elif getattr(mod, "DEFER_SCHEMA_REGISTRATION", False):
                raise ValueError("only the configured accounting schema may defer registration")
        except Exception as exc:
            raise PluginLoadError(f"configured plugin {name} schema rejected: {exc}") from exc
        try:
            plugin_name = mod.PLUGIN_NAME
            if not isinstance(plugin_name, str) or not plugin_name.isascii() or not plugin_name.isidentifier():
                raise ValueError("PLUGIN_NAME must be an ASCII identifier used as an operation prefix")
            if plugin_name in plugin_names:
                raise ValueError(f"PLUGIN_NAME {plugin_name!r} is already registered or reserved")
            if late_accounting and (plugin_name != "accounting" or getattr(mod.Plugin, "GOVERNOR", None) is not True):
                raise ValueError("accounting must own its fixed prefix and approval governor")
            if not isinstance(mod.Plugin, type):
                raise TypeError("Plugin must be a class")
            for method in ("manifest_for", "apply", "state"):
                if not callable(getattr(mod.Plugin, method, None)):
                    raise TypeError(f"Plugin must expose callable {method}")
        except Exception as exc:
            raise PluginLoadError(f"configured plugin {name} initialization contract rejected: {exc}") from exc
        try:
            if not late_accounting:
                register_schema_version(schema_name, list(statements))
        except Exception as exc:
            raise PluginLoadError(f"configured plugin {name} schema rejected: {exc}") from exc
        plugin_names.add(plugin_name)
        loaded.append(mod)
    # Publish only a complete set.  Earlier schema registrations remain idempotent
    # on retry, including entries a module registers itself during import.
    _LOADED_PLUGIN_MODULES = loaded
    return _LOADED_PLUGIN_MODULES


_load_plugin_modules()
from .core.audit import Audit, register_audit_schema
from .core.api_receipts import APIActionReceipts, register_api_receipts_schema, register_api_preparation_receipts_schema, register_api_exception_receipts_schema, register_api_accounting_receipts_schema
from .core.commands import CommandResult, Commands
from .core.db import Database, register_workspace_mode_schema
from .core.ids import new_id, parse_iso, sha256_hex, utcnow, utcnow_iso
from .core.money import fmt, money
from .domain.bills import Bills, register_bill_posting_schema
from .domain.commitments import Commitments
from .domain.estimates import Estimates
from .domain.evidence import Evidence
from .domain.forecast import Forecast
from .domain.ledger import Ledger
from .domain.payments import Payments, SimulatedProvider
from .domain.receivables import Receivables
from .domain.ricky import Ricky
from .ricky_sdk import RickySDK

# Append only after every historical domain and SDK schema has registered.
register_audit_schema()
register_bill_posting_schema()
register_workspace_mode_schema()
register_api_receipts_schema()
register_api_preparation_receipts_schema()
register_api_exception_receipts_schema()

# Only this already validated configured module is deferred. The module has no
# import registration, and the complete existing catalog remains in its order.
_accounting_module = next((mod for mod in _LOADED_PLUGIN_MODULES
                           if mod.__name__ == _LATE_ACCOUNTING_MODULE), None)
if _accounting_module is None:
    raise PluginLoadError("configured accounting module is missing at late registration")
try:
    from .core import db as _accounting_schema_registry
    _accounting_history_before = tuple((version, schema, tuple(sql)) for version, schema, sql in _accounting_schema_registry.SCHEMA_CATALOG if schema != _LATE_ACCOUNTING_SCHEMA)
    _accounting_module.register_accounting_schema()
    _accounting_history_after = tuple((version, schema, tuple(sql)) for version, schema, sql in _accounting_schema_registry.SCHEMA_CATALOG if schema != _LATE_ACCOUNTING_SCHEMA)
    if _accounting_history_after != _accounting_history_before:
        raise ValueError("accounting registrar changed historical schema entries")
    _accounting_entries = [entry for entry in _accounting_schema_registry.SCHEMA_CATALOG
                           if entry[1] == _LATE_ACCOUNTING_SCHEMA]
    if (len(_accounting_entries) != 1 or _accounting_entries[0][0] != 70
            or _accounting_entries[0][2] != _accounting_module.SCHEMA_STATEMENTS):
        raise ValueError("accounting late schema does not follow the preserved catalog")
except Exception as exc:
    raise PluginLoadError("configured accounting late schema rejected") from exc

register_api_accounting_receipts_schema()


class CipherError(RuntimeError):
    pass


class RoleNotAuthorized(CipherError, PermissionError):
    pass


class CoreReconciliationChecks:
    """Pseudo-module that contributes core subledger-to-GL checks to the close
    checklist and the Ricky brief through the standard close_checks hook.  Each
    check runs only when the core domain exposes the corresponding method."""

    CHECKS = (
        ("retainage payable reconciled (2050)", "bills", "retainage_open_items"),
        ("stored materials reconciled (1300)", "bills", "stored_material_items"),
        ("retainage receivable reconciled (1150)", "receivables", "retainage_receivable_items"),
        ("provider clearing reconciled (1200)", "payments", "clearing_items"),
        ("customer deposits reconciled (2400)", "receivables", "deposits_items"),
    )

    def __init__(self, cipher: "Cipher"):
        self.c = cipher

    def close_checks(self, period_id: str) -> list[dict[str, Any]]:
        out = []
        out.extend(self.c.bills.lifecycle_integrity_checks())
        for check in APIActionReceipts(self.c.db, self.c.audit).integrity_checks():
            out.append({"check": "AP action receipts intact", "ok": check["ok"], "detail": check["message"]})
        for label, domain_name, method in self.CHECKS:
            fn = getattr(getattr(self.c, domain_name), method, None)
            if fn is None:
                continue
            r = fn()
            out.append({"check": label, "ok": bool(r.get("reconciled")), "detail": f"subledger {r.get('subledger_total')} vs control {r.get('control_balance')}"})
        return out


OPERATIONS = {
    "estimate.approve": "estimate",
    "commitment.execute": "commitment",
    "change.execute": "change",
    "bill.approve": "bill",
    "prime_bill.approve": "prime_bill",
    "payment.release": "bill",
    "payment.release_retainage": "commitment",
    "retainage.release": "commitment",
}


class Cipher:
    def __init__(self, path: str = ":memory:", *, provider: SimulatedProvider | None = None):
        if provider is not None:
            Payments.require_simulated_provider(provider)
        plugin_modules = _load_plugin_modules()
        self.db = Database(path)
        try:
            workspace_mode = self.db.require_practice_mode(allow_pending=True)
        except BaseException:
            self.db.close()
            raise
        self.audit = Audit(self.db)
        self.approvals = Approvals(self.db, self.audit)
        self.commands = Commands(self.db, self.audit)
        self.ledger = Ledger(self.db, self.audit)
        self.ledger.ensure_chart()
        self.evidence = Evidence(self.db, self.audit)
        self.estimates = Estimates(self.db, self.audit, self.evidence)
        self.commitments = Commitments(self.db, self.audit, self.estimates)
        self.bills = Bills(self.db, self.audit, self.commitments, self.ledger)
        self.receivables = Receivables(self.db, self.audit, self.ledger)
        self.payments = Payments(self.db, self.audit, self.commands, self.ledger)
        self.forecast = Forecast(self.db, self.commitments, self.ledger)
        self.ricky = Ricky(self.db, self.audit, self.estimates, self.commitments, self.bills, self.receivables, self.payments, self.ledger, plugins=lambda: self._plugins, forecast=self.forecast, core_owner=lambda op: self._core_owner(op))
        # a fresh simulator on an existing workspace continues after the references it holds
        self.provider = provider or SimulatedProvider(ref_floor=self._simulated_ref_floor())
        # provider callbacks are verified against the provider's webhook secret when it has one
        self.payments.attach_provider(self.provider, allow_legacy=not workspace_mode["runtime_authorized"])
        # a bill payment releases the open payable (after credit notes and earlier payments)
        self.payments.open_payable_for_bill = self.bills.open_payable
        self._plugins: dict[str, Any] = {}
        try:
            with self.db.transaction():
                for mod in plugin_modules:
                    try:
                        plugin = mod.Plugin(self)
                        for method in ("manifest_for", "apply", "state"):
                            if not callable(getattr(plugin, method, None)):
                                raise TypeError(f"Plugin must expose callable {method}")
                        self.register_plugin(mod.PLUGIN_NAME, plugin)
                    except Exception as exc:
                        name = getattr(mod, "__name__", repr(mod))
                        raise PluginLoadError(f"configured plugin {name} failed to initialize: {exc}") from exc
        except Exception:
            self._plugins.clear()
            self.db.close()
            raise
        self.register_plugin("core_reconciliation", CoreReconciliationChecks(self))
        self.bills.business_manifest_builder = lambda bill_id, role: self._manifest("bill.approve", bill_id, "pm")
        self.bills.posting_authorizer = self._check_bill_post
        self.bills.cancellation_authorizer = self._check_bill_cancellation
        # Ricky's typed tool surface (registers itself as the "ricky_sdk" module)
        self.sdk = RickySDK(self)
        # Plugins that post to accounts receivable (1100) expose ar_open_items(project_id)
        # so the AR subledger covers every source, not only prime bills.
        self.receivables.extra_ar_sources = lambda: [p for n, p in sorted(self._plugins.items()) if hasattr(p, "ar_open_items")]

    def _simulated_ref_floor(self) -> int:
        """The highest simulator reference (``sim_NNNNNN``) this workspace already records."""
        floor = 0
        for row in self.db.query("SELECT provider_ref FROM payment_intents WHERE provider_ref LIKE 'sim_%'"):
            tail = str(row["provider_ref"])[4:]
            if tail.isdigit():
                floor = max(floor, int(tail))
        return floor

    # ---- plugins (v2 modules register here) ------------------------------------ #

    def register_plugin(self, name: str, module: Any) -> None:
        self._plugins[name] = module

    def plugin(self, name: str) -> Any:
        return self._plugins[name]

    # ---- master data -------------------------------------------------------------- #

    def add_party(self, *, kind: str, name: str, destination: str | None = None, actor: str = "owner") -> dict[str, Any]:
        pid = new_id("pty")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO parties (id, kind, name, destination, destination_version, destination_verified, created_at) VALUES (?,?,?,?,?,0,?)", (pid, kind, name, destination, 1 if destination else 0, utcnow_iso()))
            self.audit.record(actor, "party.created", "party", pid, {"kind": kind, "name": name})
        return self.party(pid)

    def party(self, party_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM parties WHERE id=?", (party_id,))
        if row is None:
            raise CipherError(f"unknown party {party_id}")
        return row

    def parties(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM parties ORDER BY created_at")

    def verify_destination(self, party_id: str, *, destination: str, verified_by: str, channel: str = "independent call-back") -> dict[str, Any]:
        """Record an independently verified payment destination.  Any open
        approval bound to the previous destination version is invalidated."""
        with self.db.transaction() as conn:
            p = self.party(party_id)
            conn.execute("UPDATE parties SET destination=?, destination_version=destination_version+1, destination_verified=1 WHERE id=?", (destination, party_id))
            self.audit.record(verified_by, "party.destination_verified", "party", party_id, {"destination_hash": sha256_hex(destination), "version": p["destination_version"] + 1, "channel": channel})
            for ap in self.approvals.list(status="granted") + self.approvals.list(status="pending"):
                dest = ap["manifest"].get("destination") or {}
                if dest.get("party_id") == party_id:
                    self.approvals.invalidate(ap["id"], reason="payee destination changed after approval", actor=verified_by)
        return self.party(party_id)

    def create_project(self, *, name: str, entity: str, budget: str, customer_id: str | None = None, actor: str = "owner") -> dict[str, Any]:
        pid = new_id("prj")
        with self.db.transaction() as conn:
            conn.execute("INSERT INTO projects (id, name, entity, currency, customer_id, budget, created_at) VALUES (?,?,?,?,?,?,?)", (pid, name, entity, "USD", customer_id, fmt(money(budget)), utcnow_iso()))
            self.audit.record(actor, "project.created", "project", pid, {"name": name, "budget": fmt(money(budget))})
        return self.project(pid)

    def project(self, project_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM projects WHERE id=?", (project_id,))
        if row is None:
            raise CipherError(f"unknown project {project_id}")
        return row

    def projects(self) -> list[dict[str, Any]]:
        return self.db.query("SELECT * FROM projects ORDER BY created_at")

    def set_budget(self, project_id: str, budget: str, *, actor: str = "owner") -> dict[str, Any]:
        with self.db.transaction() as conn:
            conn.execute("UPDATE projects SET budget=? WHERE id=?", (fmt(money(budget)), project_id))
            self.audit.record(actor, "project.budget_set", "project", project_id, {"budget": fmt(money(budget))})
        return self.project(project_id)

    # ---- approvals ------------------------------------------------------------------ #

    def _core_domains(self) -> tuple[Any, ...]:
        """Core domain services that may own additional approval-bound operations.
        A domain opts in by defining handles(operation) -> bool plus
        manifest_for(operation, subject_id, *, actor_role) and
        apply(operation, subject_id, *, approval_id, manifest, actor, period_id)."""
        return (self.receivables, self.bills, self.payments, self.commitments, self.estimates, self.ledger, self.evidence, self.forecast)

    def _core_owner(self, operation: str) -> Any | None:
        for domain in self._core_domains():
            handles = getattr(domain, "handles", None)
            if handles is not None and handles(operation):
                return domain
        return None

    def _governors(self) -> list[tuple[str, Any]]:
        """Plugins that add policy to approvals they do not own (identity and role grants,
        high-risk payment release, contract signature).  A governor sets ``GOVERNOR = True``
        and may define any of:

        ``approval_policy(operation, manifest) -> dict | None``
            facts bound into the approval under ``manifest['governance'][name]`` (a top-level
            key, outside the owning module's material facts, which modules re-check against
            their own manifests).  The service recomputes them at execution and invalidates
            the approval (``StaleApprovalError``) when they differ, including when a governor
            that bound facts is gone.  Return None to bind nothing -- a governor that is not
            configured must bind nothing, so existing approvals are unaffected -- and keep the
            facts state-derived (no clock readings) so an unchanged world re-derives exactly
            the same facts.
        ``check_request(operation, manifest, *, actor_role, requested_by) -> None``
        ``check_grant(approval, *, approver, approver_role) -> None``
            read-only preflight checks; refuse by raising.  Grant checks run before any
            grant effects.  At an actual grant attempt, ``StaleApprovalError`` durably
            invalidates the pending approval after the grant transaction rolls back.
        ``on_grant(approval, *, approver, approver_role) -> None``
            record grant effects after all grant checks pass and the approval is granted,
            inside the same transaction.  A refusal rolls back the grant and every effect.
        ``check_execute(approval, manifest, *, actor) -> None``
            refuse by raising.  ``check_execute`` runs inside the execution transaction,
            before the approval is consumed: a refusal leaves the approval granted unless it
            raises ``StaleApprovalError``, which invalidates it.

        Governors run in plugin-name order."""
        return [(n, p) for n, p in sorted(self._plugins.items()) if getattr(p, "GOVERNOR", False) is True]

    def _manifest(self, operation: str, subject_id: str, actor_role: str) -> dict[str, Any]:
        self.db.require_practice_mode()
        manifest = self._base_manifest(operation, subject_id, actor_role)
        bound: dict[str, Any] = {}
        for name, governor in self._governors():
            policy = getattr(governor, "approval_policy", None)
            if policy is not None:
                facts = policy(operation, manifest)
                if facts:
                    bound[name] = facts
        if bound:
            manifest["governance"] = bound
        return manifest

    def _base_manifest(self, operation: str, subject_id: str, actor_role: str) -> dict[str, Any]:
        owner = self._core_owner(operation)
        if owner is not None:
            return owner.manifest_for(operation, subject_id, actor_role=actor_role)
        if operation == "estimate.approve":
            return self.estimates.manifest(subject_id, actor_role=actor_role)
        if operation == "commitment.execute":
            return self.commitments.manifest(subject_id, actor_role=actor_role)
        if operation == "change.execute":
            return self.commitments.change_manifest(subject_id, actor_role=actor_role)
        if operation == "bill.approve":
            return self.bills.manifest(subject_id, actor_role="pm")
        if operation == "prime_bill.approve":
            return self.receivables.manifest(subject_id, actor_role=actor_role)
        if operation == "payment.release":
            return self.payments.manifest_for_bill(subject_id, actor_role=actor_role)
        if operation == "payment.release_retainage":
            m = self.payments.manifest_for_retainage(subject_id, actor_role=actor_role)
            m["operation"] = "payment.release_retainage"
            return m
        if operation == "retainage.release":
            return self.bills.retainage_manifest(subject_id, actor_role=actor_role)
        plugin = self._plugins.get(operation.split(".")[0])
        if plugin is not None and hasattr(plugin, "manifest_for"):
            return plugin.manifest_for(operation, subject_id, actor_role=actor_role)
        raise CipherError(f"unknown operation {operation}")

    def _accounting_person(self, actor, project_id):
        """An actual human's own current accountant grant and membership.

        accounting.require_accountant must verify audited people state. Owner
        wildcard, controller-only grants, delegations, service identities and
        caller-supplied role text do not supply this operation's actual duty.
        A person who is also an owner may act with their genuine accountant grant.
        """
        from .domain.accounting import AccountingError
        from .domain.people import IdentityRefused
        try:
            return self.plugin("accounting").require_accountant(actor, project_id)
        except AccountingError as exc:
            raise IdentityRefused("Accounting handoff requires the person's own current project accountant duty") from exc

    def check_accounting_queue_request(self, plan_id, *, requested_by, actor_role="accountant"):
        from .domain.people import IdentityRefused
        with self.db._lock:
            self.db.require_practice_mode()
            if actor_role != "accountant":
                raise IdentityRefused("Accounting handoff requests require the actual accountant duty")
            module = self.plugin("accounting")
            scope = module.plan_scope(plan_id)  # minimal project reference; no payload disclosed
            person = self._accounting_person(requested_by, scope["projectId"])
            checked = module.queue_preflight(plan_id)
            manifest = self._manifest("accounting.queue", plan_id, "accountant")
            for _name, governor in self._governors():
                check = getattr(governor, "check_request", None)
                if check is not None:
                    check("accounting.queue", manifest, actor_role="accountant", requested_by=requested_by)
            return {"person": person, "project_id": scope["projectId"], "manifest": manifest, "plan": checked}

    def _accounting_queue_current(self, approval_id, *, status, actor):
        """Resolve current actor scope before material source or provider facts."""
        from .domain.accounting import AccountingError
        self.db.require_practice_mode()
        approval = self.approvals.get(approval_id)
        if approval["operation"] != "accounting.queue" or approval["subject_type"] != "accounting_plan":
            raise ApprovalError("This operation requires its own accounting handoff approval")
        module = self.plugin("accounting")
        scope = module.plan_scope(approval["subject_id"])
        person = self._accounting_person(actor, scope["projectId"])
        module.approval_proof(approval_id)
        if approval["status"] == "expired":
            raise ApprovalExpired("The accounting handoff approval expired")
        if approval["status"] != status:
            raise ApprovalError("The accounting handoff approval is no longer available")
        if parse_iso(approval["expires_at"]) <= utcnow():
            raise ApprovalExpired("The accounting handoff approval expired")
        try:
            checked = module.queue_preflight(approval["subject_id"])
            current = self._manifest("accounting.queue", approval["subject_id"], "accountant")
        except AccountingError as exc:
            raise StaleApprovalError("The accounting source or mapping no longer permits this handoff") from exc
        if (material_hash(current) != approval["material_hash"]
                or current.get("governance") != approval["manifest"].get("governance")):
            raise StaleApprovalError("The accounting source, mapping or governed policy changed")
        return {"approval": approval, "person": person, "project_id": scope["projectId"],
                "manifest": current, "plan": checked, "governors": self._governors()}

    def check_accounting_queue_grant(self, approval_id, *, approver, approver_role="accountant"):
        from .domain.people import IdentityRefused
        with self.db._lock:
            if approver_role != "accountant":
                raise IdentityRefused("Accounting handoff review requires the actual accountant duty")
            checked = self._accounting_queue_current(approval_id, status="pending", actor=approver)
            people = self.plugin("people")
            if people.same_person(approver, checked["approval"]["requested_by"]):
                raise IdentityRefused("A different accountant must review this accounting handoff")
            for _name, governor in checked["governors"]:
                check = getattr(governor, "check_grant", None)
                if check is not None:
                    check(checked["approval"], approver=approver, approver_role="accountant")
            return checked

    def check_accounting_queue_execution(self, approval_id, *, actor):
        from .domain.people import IdentityRefused
        with self.db._lock:
            checked = self._accounting_queue_current(approval_id, status="granted", actor=actor)
            original_approver = checked["approval"]["approver"]
            try:
                self._accounting_person(original_approver, checked["project_id"])
            except IdentityRefused as exc:
                raise StaleApprovalError("The original accounting reviewer no longer holds the required duty") from exc
            for name, governor in checked["governors"]:
                effect_check = getattr(governor, "check_execute", None)
                if effect_check is None:
                    continue
                check = effect_check if name == "people" else getattr(governor, "check_execute_preflight", None)
                if check is None:
                    raise ApprovalError("A configured governor cannot provide a pure accounting handoff review")
                check(checked["approval"], checked["manifest"], actor=actor)
            return checked

    def check_request_approval(self, operation: str, subject_id: str, *, actor_role: str = "owner", requested_by: str = "owner") -> dict[str, Any]:
        """Build and check the request without creating an approval or audit entry."""
        if operation == "accounting.queue":
            return self.check_accounting_queue_request(subject_id, requested_by=requested_by, actor_role=actor_role)["manifest"]
        manifest = self._manifest(operation, subject_id, actor_role)  # modules may refuse first with their own error
        if operation == "bill.approve":
            people = self._plugins.get("people")
            if people is None or not callable(getattr(people, "check_bill_request", None)):
                raise RoleNotAuthorized("Bill preparation requires the configured identity governor.")
            people.check_bill_request(manifest, actor_role=actor_role, requested_by=requested_by)
        elif not Ricky.can(actor_role, operation):
            raise RoleNotAuthorized(f"role {actor_role!r} is not authorized for {operation}")
        for _name, governor in self._governors():
            if operation == "bill.approve" and _name == "people":
                continue  # its preparation and decision duties are separate
            check = getattr(governor, "check_request", None)
            if check is not None:
                check(operation, manifest, actor_role=actor_role, requested_by=requested_by)
        return manifest

    def request_approval(self, operation: str, subject_id: str, *, actor_role: str = "owner", requested_by: str = "owner") -> dict[str, Any]:
        """The manifest's actor_role is the role that will execute the operation; it
        must hold that authority (ROLE_AUTHORITY), exactly as Ricky enforces."""
        if operation == "accounting.queue":
            with self.db.transaction() as conn:
                savepoint = new_id("accounting_request")
                conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    manifest = self.check_request_approval(operation, subject_id, actor_role=actor_role, requested_by=requested_by)
                    return self.approvals.request(manifest, requested_by=requested_by)
                except BaseException:
                    if conn.in_transaction:
                        conn.execute(f"ROLLBACK TO {savepoint}")
                    raise
                finally:
                    if conn.in_transaction:
                        conn.execute(f"RELEASE {savepoint}")
        manifest = self.check_request_approval(operation, subject_id, actor_role=actor_role, requested_by=requested_by)
        return self.approvals.request(manifest, requested_by=requested_by)

    def check_approval_grant(self, approval_id: str, *, approver: str = "owner", approver_role: str = "owner") -> dict[str, Any]:
        """Check human decision authority and bill facts without granting anything."""
        self.db.require_practice_mode()
        ap = self.approvals.get(approval_id)
        if ap["operation"] == "ap_intake.match_invoice":
            return self.check_invoice_match_grant(approval_id, approver=approver, approver_role=approver_role)
        if ap["operation"] == "bill.correct":
            return self.check_bill_correction_grant(approval_id, approver=approver, approver_role=approver_role)
        if ap["operation"] == "accounting.queue":
            return self.check_accounting_queue_grant(approval_id, approver=approver, approver_role=approver_role)
        if not Ricky.can(approver_role, ap["operation"]):
            raise RoleNotAuthorized(f"role {approver_role!r} cannot approve {ap['operation']}")
        governors = self._governors()
        for name, governor in governors:
            check = getattr(governor, "check_bill_grant" if ap["operation"] == "bill.approve" and name == "people" else "check_grant", None)
            if check is not None:
                check(ap, approver=approver, approver_role=approver_role)
        if ap["operation"] == "bill.approve" and ap["status"] == "pending":
            self.bills.business_grant_preflight(ap["subject_id"], approval_id=approval_id)
        return {"approval": ap, "governors": governors}

    def _invoice_match_current(self, approval_id: str, *, status: str) -> dict[str, Any]:
        """Check one fixed match operation, with no lifecycle writes or effects."""
        from .core.approvals import ApprovalConsumed, ApprovalError, ApprovalNotGranted, material_hash
        from .core.ids import parse_iso, utcnow
        self.db.require_practice_mode()
        self.plugin("ap_intake").approval_proof(approval_id)
        approval = self.approvals.get(approval_id)
        if approval["status"] == "expired":
            raise ApprovalExpired("The match authorization expired")
        if approval["status"] != status:
            if status == "granted":
                if approval["status"] == "consumed":
                    raise ApprovalConsumed("The match authorization was already consumed")
                raise ApprovalNotGranted("The match authorization is no longer granted")
            raise ApprovalError("The match authorization is no longer available")
        if parse_iso(approval["expires_at"]) <= utcnow():
            raise ApprovalExpired("The match authorization expired")
        manifest = self._manifest("ap_intake.match_invoice", approval["subject_id"], approval["actor_role"])
        if (material_hash(manifest) != approval["material_hash"]
                or manifest.get("governance") != approval["manifest"].get("governance")):
            raise StaleApprovalError("The match authorization no longer matches its governed source facts")
        return {"approval": approval, "manifest": manifest, "governors": self._governors()}

    def check_invoice_match_grant(self, approval_id: str, *, approver: str = "owner", approver_role: str = "owner") -> dict[str, Any]:
        """Verify current match facts and independent grant authority without writing."""
        checked = self._invoice_match_current(approval_id, status="pending")
        approval = checked["approval"]
        if not Ricky.can(approver_role, "ap_intake.match_invoice"):
            raise RoleNotAuthorized("This role cannot approve a supplier invoice match")
        for _name, governor in checked["governors"]:
            check = getattr(governor, "check_grant", None)
            if check is not None:
                check(approval, approver=approver, approver_role=approver_role)
        return checked

    def check_invoice_match_execution(self, approval_id: str, *, actor: str = "owner") -> dict[str, Any]:
        """Verify the granted match with explicitly pure governor counterparts."""
        checked = self._invoice_match_current(approval_id, status="granted")
        for name, governor in checked["governors"]:
            effect_check = getattr(governor, "check_execute", None)
            if effect_check is None:
                continue
            # The registry's execute check is read-only. Other governors must
            # declare a pure counterpart, never run an effect and roll it back.
            check = effect_check if name == "people" else getattr(governor, "check_execute_preflight", None)
            if check is None:
                raise CipherError("A configured governor does not support a pure invoice match check")
            check(checked["approval"], checked["manifest"], actor=actor)
        return checked

    def _bill_correction_current(self, approval_id: str, *, status: str) -> dict[str, Any]:
        from .core.approvals import ApprovalConsumed, ApprovalError, ApprovalNotGranted, material_hash
        from .core.ids import parse_iso, utcnow
        self.db.require_practice_mode()
        self.bills.correction_approval_proof(approval_id)
        approval = self.approvals.get(approval_id)
        if approval["status"] == "expired":
            raise ApprovalExpired("The correction authorization expired")
        if approval["status"] != status:
            if status == "granted":
                if approval["status"] == "consumed":
                    raise ApprovalConsumed("The correction authorization was already consumed")
                raise ApprovalNotGranted("The correction authorization is no longer granted")
            raise ApprovalError("The correction authorization is no longer available")
        if parse_iso(approval["expires_at"]) <= utcnow():
            raise ApprovalExpired("The correction authorization expired")
        manifest = self._manifest("bill.correct", approval["subject_id"], approval["actor_role"])
        if (material_hash(manifest) != approval["material_hash"]
                or manifest.get("governance") != approval["manifest"].get("governance")):
            raise StaleApprovalError("The correction authorization no longer matches its governed source facts")
        return {"approval": approval, "manifest": manifest, "governors": self._governors()}

    def check_bill_correction_grant(self, approval_id: str, *, approver: str = "owner", approver_role: str = "owner") -> dict[str, Any]:
        """Verify the fixed bill correction and independent grant duty without effects."""
        checked = self._bill_correction_current(approval_id, status="pending")
        if not Ricky.can(approver_role, "bill.correct"):
            raise RoleNotAuthorized("This role cannot approve a bill correction")
        for _name, governor in checked["governors"]:
            check = getattr(governor, "check_grant", None)
            if check is not None:
                check(checked["approval"], approver=approver, approver_role=approver_role)
        return checked

    def check_bill_correction_execution(self, approval_id: str, *, actor: str = "owner", period_id: str | None = None) -> dict[str, Any]:
        """Calculate the exact reversal plan through declared pure governor checks."""
        checked = self._bill_correction_current(approval_id, status="granted")
        for name, governor in checked["governors"]:
            effect_check = getattr(governor, "check_execute", None)
            if effect_check is None:
                continue
            check = effect_check if name == "people" else getattr(governor, "check_execute_preflight", None)
            if check is None:
                raise CipherError("A configured governor does not support a pure bill correction check")
            check(checked["approval"], checked["manifest"], actor=actor)
        plan = self.bills.correction_execution_preflight(checked["approval"]["subject_id"], period_id=period_id,
                                                        approval_id=approval_id, manifest=checked["manifest"])
        checked.update(plan)
        checked["plan"] = plan
        return checked

    def approve(self, approval_id: str, *, approver: str = "owner", approver_role: str = "owner") -> dict[str, Any]:
        """Grant an approval.  The approver's role must hold the operation's authority.
        A sole owner holds every role; two owner logins are not two-person separation
        (plan v1.1), which is why releases also need the independent controls in payments."""
        self.db.require_practice_mode()
        try:
            with self.db.transaction() as conn:
                # A caught refusal must also undo grant effects when our transaction
                # joins a caller's outer transaction.  The identifier is generated here.
                savepoint = new_id("grant")
                conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    checked = self.check_approval_grant(approval_id, approver=approver, approver_role=approver_role)
                    ap, governors = checked["approval"], checked["governors"]
                    granted = self.approvals.grant(approval_id, approver=approver)
                    for _name, governor in governors:
                        hook = getattr(governor, "on_grant", None)
                        if hook is not None:
                            hook(granted, approver=approver, approver_role=approver_role)
                    if ap["operation"] == "bill.approve":
                        self.bills.record_business_approval(ap["subject_id"], approval_id=approval_id, actor=approver)
                except BaseException:
                    if conn.in_transaction:
                        conn.execute(f"ROLLBACK TO {savepoint}")
                    raise
                finally:
                    if conn.in_transaction:
                        conn.execute(f"RELEASE {savepoint}")
                return granted
        except StaleApprovalError as exc:
            # Grant checks and effects rolled back; preserve a stale attempt durably.
            with self.db.transaction():
                if self.approvals.get(approval_id)["status"] == "pending":
                    self.approvals.invalidate(approval_id, reason=str(exc), actor=approver)
            raise
        except ApprovalExpired:
            # Approvals.grant's expiry write joined the transaction that rolled back.
            with self.db.transaction():
                if self.approvals.get(approval_id)["status"] == "pending":
                    self.approvals.mark_expired(approval_id, actor=approver)
            raise

    def reject(self, approval_id: str, *, approver: str = "owner", reason: str = "") -> dict[str, Any]:
        return self.approvals.reject(approval_id, approver=approver, reason=reason)

    def execute(self, approval_id: str, *, actor: str = "owner", op_id: str | None = None, period_id: str | None = None) -> CommandResult:
        self.db.require_practice_mode()
        ap = self.approvals.get(approval_id)
        operation, subject_id = ap["operation"], ap["subject_id"]
        if operation == "bill.approve":
            raise CipherError("Bill business approval does not post. An independent accounting person must use post_bill.")
        op_id = op_id or f"exec:{approval_id}"
        payload = {"approval_id": approval_id, "operation": operation, "subject_id": subject_id}
        if operation == "accounting.queue":
            if period_id is not None:
                raise ApprovalError("Accounting handoff uses only its original bound posting period")
            module = self.plugin("accounting")
            scope = module.plan_scope(subject_id)
            person = self._accounting_person(actor, scope["projectId"])
            module.approval_proof(approval_id)
            payload["person_id"] = person["personId"]

        def apply_handler():
            current = (self.check_invoice_match_execution(approval_id, actor=actor)["manifest"]
                       if operation == "ap_intake.match_invoice" else
                       self.check_bill_correction_execution(approval_id, actor=actor, period_id=period_id)["manifest"]
                       if operation == "bill.correct" else
                       self.check_accounting_queue_execution(approval_id, actor=actor)["manifest"]
                       if operation == "accounting.queue" else self._manifest(operation, subject_id, ap["actor_role"]))
            fresh = self.approvals.get(approval_id)
            approved_policy, current_policy = fresh["manifest"].get("governance"), current.get("governance")
            if fresh["status"] == "granted" and approved_policy != current_policy:
                changed = sorted(k for k in set(approved_policy or {}) | set(current_policy or {})
                                 if (approved_policy or {}).get(k) != (current_policy or {}).get(k))
                raise StaleApprovalError(f"approval {approval_id} no longer matches the policy it was granted under: {', '.join(changed)} changed")
            for _name, governor in self._governors():
                check = getattr(governor, "check_execute", None)
                if check is not None:
                    check(fresh, current, actor=actor)
            self.approvals.consume(approval_id, current_manifest=current, consumer=actor)
            return self._apply(operation, subject_id, approval_id, current, actor, period_id)

        def governed_command():
            # Commands joins an outer transaction. Include its bookkeeping in
            # this boundary so a caught late failure cannot leave consumption,
            # reversals, correction state or an incomplete command behind.
            with self.db.transaction() as conn:
                savepoint = new_id("accounting_queue_act" if operation == "accounting.queue" else "bill_correction_act")
                conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    result = self.commands.run(op_id, payload, apply_handler, actor=actor)
                    if operation == "accounting.queue":
                        intents = [row for row in module.intent_inventory(project_ids=(scope["projectId"],))
                                   if row["approval_id"] == approval_id]
                        if len(intents) != 1:
                            raise ApprovalError("Accounting command lost its original queued intent")
                        original = intents[0]
                        expected = {"intent_id": original["id"], "logical_operation_id": original["logical_operation_id"],
                                    "status": "queued", "mode": "practice", "synthetic": True}
                        if result.result != expected:
                            raise ApprovalError("Accounting command result differs from its original queued effect")
                    return result
                except BaseException:
                    if conn.in_transaction:
                        conn.execute(f"ROLLBACK TO {savepoint}")
                    raise
                finally:
                    if conn.in_transaction:
                        conn.execute(f"RELEASE {savepoint}")

        try:
            return (governed_command() if operation in ("bill.correct", "accounting.queue") else
                    self.commands.run(op_id, payload, apply_handler, actor=actor))
        except StaleApprovalError as exc:
            # the command transaction rolled back; make the invalidation durable
            if self.approvals.get(approval_id)["status"] == "granted":
                self.approvals.invalidate(approval_id, reason=str(exc), actor=actor)
            raise
        except ApprovalExpired:
            # likewise make the expiry durable, so the approval leaves every execute list
            if self.approvals.get(approval_id)["status"] == "granted":
                self.approvals.mark_expired(approval_id, actor=actor)
            raise

    def _apply(self, operation: str, subject_id: str, approval_id: str, manifest: dict[str, Any], actor: str, period_id: str | None) -> dict[str, Any]:
        owner = self._core_owner(operation)
        if owner is not None:
            return owner.apply(operation, subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        if operation == "estimate.approve":
            return {"estimate": self.estimates.approve(subject_id, approval_id=approval_id, actor=actor)["id"], "status": "approved"}
        if operation == "commitment.execute":
            c = self.commitments.execute(subject_id, approval_id=approval_id, actor=actor)
            return {"commitment": c["id"], "status": c["status"], "executed_amount": c["executed_amount"]}
        if operation == "change.execute":
            ch = self.commitments.execute_change(subject_id, approval_id=approval_id, actor=actor)
            for b in self.bills.list(commitment_id=ch["commitment_id"]):
                if b["status"] in ("draft", "approved"):
                    self.approvals.invalidate_for_subject("bill", b["id"], reason="commitment changed after the bill was certified", actor=actor)
            c = self.commitments.get(ch["commitment_id"])
            return {"change": ch["id"], "commitment_executed_amount": c["executed_amount"], "commitment_version": c["version"]}
        if operation == "bill.approve":
            raise CipherError("The combined bill approval/posting route is retired; use post_bill.")
        if operation == "prime_bill.approve":
            b = self.receivables.post(subject_id, approval_id=approval_id, actor=actor)
            return {"prime_bill": b["id"], "status": b["status"], "journal_id": b["journal_id"]}
        if operation == "payment.release":
            intent = self.payments.create_intent(manifest=manifest, approval_id=approval_id, bill_id=subject_id, note="bill payment", actor=actor)
            return {"intent": intent["id"], "status": intent["status"], "amount": intent["amount"]}
        if operation == "payment.release_retainage":
            intent = self.payments.create_intent(manifest=manifest, approval_id=approval_id, bill_id=None, note="retainage release payment", actor=actor)
            return {"intent": intent["id"], "status": intent["status"], "amount": intent["amount"]}
        if operation == "retainage.release":
            pid = period_id or self.current_period()["id"]
            return self.bills.release_retainage(commitment_id=subject_id, period_id=pid, approval_id=approval_id, actor=actor)
        plugin = self._plugins.get(operation.split(".")[0])
        if plugin is not None and hasattr(plugin, "apply"):
            return plugin.apply(operation, subject_id, approval_id=approval_id, manifest=manifest, actor=actor, period_id=period_id)
        raise CipherError(f"unknown operation {operation}")

    def approve_and_execute(self, operation: str, subject_id: str, *, actor_role: str = "owner", actor: str = "owner", period_id: str | None = None) -> CommandResult:
        """Convenience for scripts and tests: request, grant and execute in one go.
        Each step is still recorded separately."""
        if operation == "bill.approve":
            raise CipherError("Bill business approval and posting require separate people and explicit acts.")
        ap = self.request_approval(operation, subject_id, actor_role=actor_role, requested_by=actor)
        self.approve(ap["id"], approver=actor)
        return self.execute(ap["id"], actor=actor, period_id=period_id)

    def _check_bill_post(self, approval: dict[str, Any], manifest: dict[str, Any], actor: str, period_id: str,
                         *, actor_role: str = "accountant") -> None:
        people = self._plugins.get("people")
        if people is None or not callable(getattr(people, "check_bill_post", None)):
            raise RoleNotAuthorized("Bill posting requires the configured identity governor.")
        if approval["manifest"].get("governance") != manifest.get("governance"):
            raise StaleApprovalError("Bill approval no longer matches its governed policy; request fresh approval.")
        people.check_bill_post(approval, manifest, actor=actor, actor_role=actor_role)
        for name, governor in self._governors():
            if name == "people":
                continue
            check = getattr(governor, "check_execute", None)
            if check is not None:
                check(approval, manifest, actor=actor)

    def _check_bill_cancellation(self, approval: dict[str, Any], manifest: dict[str, Any], actor: str) -> None:
        people = self._plugins.get("people")
        if people is None or not callable(getattr(people, "check_bill_cancellation", None)):
            raise RoleNotAuthorized("Withdrawing an approved bill requires its human business approver.")
        people.check_bill_cancellation(approval, actor=actor)

    def check_bill_posting(self, bill_id: str, *, actor: str, actor_role: str = "accountant", period_id: str | None = None,
                           reason: str = "") -> dict[str, Any]:
        """Read-only eligibility and exact posting plan for a human's review."""
        self.db.require_practice_mode()
        bill = self.bills.get(bill_id)
        approval_id = bill.get("business_approval_id")
        if not approval_id:
            raise CipherError("This bill has no recorded business approval for independent posting.")
        checked = self.bills.posting_preflight(bill_id, approval_id=approval_id, actor=actor, actor_role=actor_role,
                                               period_id=period_id, reason=reason)
        ap, manifest = checked["approval"], checked["manifest"]
        people = self._plugins.get("people")
        if people is None or not callable(getattr(people, "check_bill_post", None)):
            raise RoleNotAuthorized("Bill posting requires the configured identity governor.")
        people.check_bill_post(ap, manifest, actor=actor, actor_role=actor_role)
        for name, governor in self._governors():
            if name == "people":
                continue
            check = getattr(governor, "check_execute_preflight", None)
            if check is not None:
                check(ap, manifest, actor=actor)
            elif callable(getattr(governor, "check_execute", None)):
                # Effectful execution hooks are not safe preview hooks.
                raise CipherError("A configured bill governor does not support read-only review.")
        return checked

    def post_bill(self, bill_id: str, *, actor: str, actor_role: str = "accountant", period_id: str | None = None,
                  reason: str = "", op_id: str | None = None) -> CommandResult:
        """Post once under the bill's original human business authorization.

        The domain rechecks/consumes that grant and seals the actual posting receipt.
        This synthetic facade receives a declared duty; the live API must derive
        identity/duties from its authenticated session, never request-body claims.
        """
        self.db.require_practice_mode()
        if not isinstance(actor, str) or not actor.strip():
            raise RoleNotAuthorized("Name the independent accounting person posting this bill.")
        bill = self.bills.get(bill_id)
        approval_id = bill.get("business_approval_id")
        if not approval_id:
            raise CipherError("This bill has no recorded business approval for independent posting.")
        if self.approvals.get(approval_id)["status"] == "invalidated":
            raise StaleApprovalError("The bill's business approval was invalidated; request fresh approval before posting.")
        selected_period = period_id or bill["period_id"]
        payload = {"operation": "bill.post", "bill_id": bill_id, "approval_id": approval_id,
                   "period_id": selected_period, "reason": reason, "actor": actor.strip().casefold(), "actor_role": actor_role}
        op_id = op_id or f"bill.post:{bill_id}:{approval_id}"

        def result_for(posted, receipt):
            return {"bill": posted["id"], "status": "posted", "journal_id": posted["journal_id"],
                    "amount_due": posted["amount_due"], "posting_receipt_id": receipt["id"],
                    "posting_period_id": receipt["period_id"]}

        def handler():
            posted = self.bills.post(bill_id, approval_id=approval_id, actor=actor, actor_role=actor_role,
                                     period_id=selected_period, reason=reason)
            return result_for(posted, self.bills.posting_receipt(bill_id))

        try:
            with self.db.transaction() as conn:
                savepoint = new_id("post")
                conn.execute(f"SAVEPOINT {savepoint}")
                try:
                    receipt = self.bills.posting_receipt(bill_id)
                    if receipt is not None:
                        people = self._plugins.get("people")
                        if people is None:
                            raise RoleNotAuthorized("Bill posting requires the configured identity governor.")
                        people.check_bill_post(self.approvals.get(approval_id), actor=actor, actor_role=actor_role, replay=True)
                    result = self.commands.run(op_id, payload, handler, actor=actor)
                    if result.replayed:
                        receipt = self.bills.posting_receipt(bill_id)
                        if receipt is None or result.result != result_for(self.bills.get(bill_id), receipt):
                            raise CipherError("The cached posting result does not match its immutable audited receipt.")
                except BaseException:
                    if conn.in_transaction:
                        conn.execute(f"ROLLBACK TO {savepoint}")
                    raise
                finally:
                    if conn.in_transaction:
                        conn.execute(f"RELEASE {savepoint}")
                return result
        except StaleApprovalError as exc:
            if self.approvals.get(approval_id)["status"] == "granted":
                self.approvals.invalidate(approval_id, reason=str(exc), actor=actor)
            raise
        except ApprovalExpired:
            if self.approvals.get(approval_id)["status"] == "granted":
                self.approvals.mark_expired(approval_id, actor=actor)
            raise

    # ---- periods ------------------------------------------------------------------------ #

    def open_period(self, period_id: str, name: str, start_date: str, end_date: str, *, actor: str = "owner") -> dict[str, Any]:
        return self.ledger.open_period(period_id, name, start_date, end_date, actor=actor)

    def current_period(self) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM periods WHERE status='open' ORDER BY start_date DESC LIMIT 1")
        if row is None:
            raise CipherError("no open period")
        return row

    def close_period(self, period_id: str, *, actor: str = "owner") -> dict[str, Any]:
        """Low-level close used by fixtures.  Interactive surfaces (HTTP, console) go
        through the close module's checklist approval ("close.close_period")."""
        return self.ledger.close_period(period_id, actor=actor)

    def close_commitment(self, commitment_id: str, *, actor: str = "owner") -> dict[str, Any]:
        """Close a commitment from an interactive surface.  When the field module is
        registered, closing happens only through its accepted closeout
        ("field.accept_closeout"), which is what lets retainage be released."""
        field = self._plugins.get("field")
        if field is not None:
            accepted = getattr(field, "closeout_accepted", None)
            if accepted is None or not accepted(commitment_id):
                raise CipherError("closeout has not been accepted; request the field.accept_closeout approval instead")
            return self.commitments.get(commitment_id)
        return self.commitments.close(commitment_id, actor=actor)

    # ---- payments -------------------------------------------------------------------------- #

    def dispatch_payments(self, *, actor: str = "treasury-worker") -> list[dict[str, Any]]:
        return self.payments.dispatch_pending(self.provider, actor=actor)

    def reconcile_payments(self, *, actor: str = "reconciler") -> list[dict[str, Any]]:
        return self.payments.reconcile(self.provider, actor=actor)

    # ---- reading ------------------------------------------------------------------------------ #

    def project_state(self, project_id: str) -> dict[str, Any]:
        workspace_mode = self.db.require_practice_mode(allow_pending=True)
        project = self.project(project_id)
        commitments = self.commitments.list(project_id)
        for c in commitments:
            c["bills"] = self.bills.list(commitment_id=c["id"])
            c["stored_lots"] = self.bills.lots(c["id"])
        state = {
            "project": project,
            "authority": self.db.authority_status(),
            "workspace_mode": workspace_mode,
            "periods": self.ledger.periods(),
            "parties": self.parties(),
            "documents": self.evidence.documents(project_id),
            "estimates": self.estimates.list(project_id),
            "commitments": commitments,
            "prime_bills": self.receivables.list(project_id),
            "payments": self.payments.list(),
            "approvals": self.approvals.list(),
            "forecast": self.forecast.project(project_id),
            "ap": self.bills.ap_open_items(project_id),
            "ar": self.receivables.ar_open_items(project_id),
            "trial_balance": self.ledger.trial_balance(),
            "income_statement": self.ledger.income_statement(),
            "ricky": self.ricky.history(20),
            "ricky_brief": self.ricky.brief(project_id, actor_role="owner"),
            "audit_chain": self.audit.verify_chain(),
            "outbox_pending": self.commands.pending(),
        }
        for name, plugin in self._plugins.items():
            if hasattr(plugin, "state"):
                state[name] = plugin.state(project_id)
        return state

    def audit_export(self) -> dict[str, Any]:
        """Everything an independent reviewer needs to re-perform the books: chart,
        periods, journals, approvals, source records with their evidence hashes,
        payment execution history, subledger reconciliations, every module's own
        records (via its optional audit_export() hook), the schema manifest and the
        hash-chained audit log."""
        workspace_mode = self.db.require_practice_mode(allow_pending=True)
        q = self.db.query
        modules: dict[str, Any] = {}
        for name, plugin in sorted(self._plugins.items()):
            fn = getattr(plugin, "audit_export", None)
            if fn is not None:
                try:
                    modules[name] = fn()
                except Exception as exc:  # an export must say what it could not include
                    modules[name] = {"error": f"{type(exc).__name__}: {exc}"}
        reconciliations: dict[str, Any] = {"ap": self.bills.ap_open_items(), "ar": self.receivables.ar_open_items()}
        for label, domain_name, method in CoreReconciliationChecks.CHECKS:
            fn = getattr(getattr(self, domain_name), method, None)
            if fn is not None:
                reconciliations[label] = fn()
        core_exports: dict[str, Any] = {}
        for domain in self._core_domains():
            fn = getattr(domain, "audit_export", None)
            if fn is not None:
                try:
                    core_exports[type(domain).__name__.lower()] = fn()
                except Exception as exc:
                    core_exports[type(domain).__name__.lower()] = {"error": f"{type(exc).__name__}: {exc}"}
        close_checks: dict[str, Any] = {}
        for period in self.db.query("SELECT id FROM periods WHERE status='open' ORDER BY start_date"):
            checks = []
            for name, plugin in sorted(self._plugins.items()):
                if hasattr(plugin, "close_checks"):
                    try:
                        checks.extend({**chk, "source": name} for chk in (plugin.close_checks(period["id"]) or []))
                    except Exception as exc:
                        checks.append({"check": f"{name} close checks", "ok": False, "detail": str(exc), "source": name})
            close_checks[period["id"]] = checks
        return {
            "exported_at": utcnow_iso(),
            "workspace": self.db.authority_status(),
            "workspace_mode": workspace_mode,
            "schema": self.db.schema_manifest(),
            "chart_of_accounts": self.ledger.accounts(),
            "periods": self.ledger.periods(),
            "trial_balance": self.ledger.trial_balance(),
            "journals": self.ledger.journals(),
            "approvals": self.approvals.list(),
            "ap_reconciliation": reconciliations["ap"],
            "ap_action_receipts": {
                "records": q("SELECT * FROM ap_action_receipts ORDER BY created_at, id"),
                "integrity": APIActionReceipts(self.db, self.audit).integrity_checks(),
            },
            "ar_reconciliation": reconciliations["ar"],
            "source_records": {
                "parties": q("SELECT id, kind, name, destination_version, destination_verified, created_at FROM parties ORDER BY created_at"),
                "projects": q("SELECT * FROM projects ORDER BY created_at"),
                "documents": q("SELECT * FROM documents ORDER BY created_at"),
                "document_revisions": q("SELECT * FROM document_revisions ORDER BY created_at"),
                "estimates": q("SELECT * FROM estimates ORDER BY created_at"),
                "estimate_lines": q("SELECT * FROM estimate_lines ORDER BY estimate_id, line_no"),
                "commitments": q("SELECT * FROM commitments ORDER BY created_at"),
                "sov_lines": q("SELECT * FROM sov_lines ORDER BY commitment_id, line_no"),
                "changes": q("SELECT * FROM changes ORDER BY created_at"),
                "stored_material_lots": q("SELECT * FROM stored_material_lots ORDER BY created_at"),
                "bills": q("SELECT * FROM bills ORDER BY created_at"),
                "bill_lines": q("SELECT * FROM bill_lines ORDER BY bill_id"),
                "prime_bills": q("SELECT * FROM prime_bills ORDER BY created_at"),
                "collections": q("SELECT * FROM collections ORDER BY received_at"),
            },
            "payment_execution": {
                "intents": q("SELECT * FROM payment_intents ORDER BY created_at"),
                "provider_events": q("SELECT * FROM provider_events ORDER BY received_at"),
                "outbox": q("SELECT id, kind, status, attempts, last_error, created_at, dispatched_at FROM outbox ORDER BY created_at"),
                "idempotency": q("SELECT op_id, payload_hash, created_at FROM idempotency ORDER BY created_at"),
            },
            "reconciliations": reconciliations,
            "open_period_close_checks": close_checks,
            "core_domains": core_exports,
            "modules": modules,
            "tables": self._export_tables(),
            "ricky_proposals": q("SELECT id, workflow, actor_role, decision, reason, created_at FROM ricky_proposals ORDER BY created_at"),
            "audit": self.audit.export(),
        }

    SECRET_TABLE_MARKERS = ("redaction_key", "secret")
    REDACTED_COLUMNS = ("destination", "key_hex", "secret", "token")

    def _export_tables(self) -> dict[str, Any]:
        """Every table's rows, so nothing a module records can be missing from the
        export.  Tables holding keys are listed without rows; payee destinations and
        any key or token column are replaced by their SHA-256 fingerprint."""
        out: dict[str, Any] = {}
        for t in self.db.query("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"):
            name = t["name"]
            count = self.db.scalar(f'SELECT COUNT(*) FROM "{name}"')
            if any(m in name for m in self.SECRET_TABLE_MARKERS):
                out[name] = {"row_count": count, "rows": "withheld: holds key material"}
                continue
            rows = self.db.query(f'SELECT * FROM "{name}"')
            for r in rows:
                for col in list(r):
                    if r[col] is not None and any(m in col for m in self.REDACTED_COLUMNS):
                        r[col] = "sha256:" + sha256_hex(str(r[col]))
            out[name] = {"row_count": count, "rows": rows}
        return out

    # ---- restore ---------------------------------------------------------------------------------- #

    def snapshot(self, target_path: str) -> str:
        return self.db.snapshot(target_path)

    @classmethod
    def open_restored(cls, path: str, *, provider: SimulatedProvider | None = None) -> "Cipher":
        """Open a restored copy.  It has no write authority and payment release is
        quarantined until the owner claims authority and reconciles."""
        return cls(path, provider=provider)

    def claim_write_authority(self, *, approval_ref: str | None = None, actor: str = "owner", reason: str | None = None, claim_code: str | None = None) -> dict[str, Any]:
        """Claim write authority for a restored or copied workspace.  The claim is an
        attested owner action (approver and reason recorded; a claim code is required
        when CIPHER_OWNER_SECRET is configured) because a read-only copy cannot record
        an approval of its own."""
        reason = reason or f"claimed by {actor}"
        try:
            return self.db.claim_write_authority(approver=actor, reason=reason, approval_ref=approval_ref, claim_code=claim_code)
        except TypeError:  # older Database signature
            return self.db.claim_write_authority(approval_ref=approval_ref or reason, note=f"claimed by {actor}: {reason}")

    def complete_recovery(self, *, actor: str = "owner") -> dict[str, Any]:
        return self.payments.complete_recovery_reconciliation(self.provider, actor=actor)


# --------------------------------------------------------------------------- #
# Golden fixture                                                               #
# --------------------------------------------------------------------------- #

def run_golden_fixture(cipher: Cipher | None = None) -> dict[str, Any]:
    """Drive the plan's synthetic vertical workflow end to end and return the
    numbers the acceptance tests assert on."""
    c = cipher or Cipher()
    owner = "owner"
    supplier = c.add_party(kind="supplier", name="Synthetic Subcontractor A", destination="ACH-SIM-0001")
    c.verify_destination(supplier["id"], destination="ACH-SIM-0001", verified_by="owner")
    customer = c.add_party(kind="customer", name="Synthetic Owner Agency")
    project = c.create_project(name="Synthetic WWTP upgrade", entity="S&A Solutions LLC (synthetic)", budget="115000", customer_id=customer["id"])
    c.open_period("2026-10", "October 2026", "2026-10-01", "2026-10-31")
    c.open_period("2026-11", "November 2026", "2026-11-01", "2026-11-30")

    drawing = c.evidence.register_document(project_id=project["id"], kind="drawing", title="Drawing A - site piping and pump station", actor=owner)
    rev1 = c.evidence.add_revision(document_id=drawing["id"], content=b"drawing A rev 1 (synthetic)", note="issued for pricing", actor=owner)
    estimate = c.estimates.create(project_id=project["id"], document_revision_id=rev1["id"], lines=[
        {"description": "Site piping", "quantity": "1", "unit": "LS", "unit_price": "60000"},
        {"description": "Pump station", "quantity": "1", "unit": "LS", "unit_price": "40000"},
    ], actor=owner)
    c.approve_and_execute("estimate.approve", estimate["id"], actor_role="owner")

    commitment = c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title="Subcontract - site piping and pump station",
                                      sov_lines=[{"description": "Site piping", "amount": "60000"}, {"description": "Pump station", "amount": "40000"}],
                                      retainage_rate="0.10", estimate_id=estimate["id"], actor=owner)
    c.approve_and_execute("commitment.execute", commitment["id"], actor_role="owner")
    line1 = c.commitments.get(commitment["id"])["sov"][0]["id"]

    change = c.commitments.propose_change(commitment["id"], amount="10000", reason="Drawing B scope addition", sov_line_id=line1, actor=owner)
    c.approve_and_execute("change.execute", change["id"], actor_role="owner")
    commitment = c.commitments.get(commitment["id"])

    # period 1
    # stored material must be backed by an evidence revision on the project (title/control, insurance, location, delivery)
    pipe_evidence = c.evidence.register_document(project_id=project["id"], kind="stored_material_evidence", title="DI pipe: bill of sale, insurance certificate, laydown photos", actor=owner)
    pipe_rev = c.evidence.add_revision(document_id=pipe_evidence["id"], content=b"synthetic stored-material evidence: DI pipe", note="title, insurance, location", actor=owner)
    lot1 = c.bills.add_stored_material(commitment_id=commitment["id"], sov_line_id=line1, description="Ductile iron pipe, on site", eligible_amount="10000", evidence_hash=pipe_rev["content_hash"], location="laydown yard", actor=owner)
    bill1 = c.bills.certify(commitment_id=commitment["id"], period_id="2026-10", installed=[{"sov_line_id": line1, "cumulative_installed": "20000"}], actor=owner)
    bill1_approval = c.request_approval("bill.approve", bill1["id"], actor_role="accountant", requested_by="accountant")
    c.approve(bill1_approval["id"], approver=owner, approver_role="owner")
    c.post_bill(bill1["id"], actor="accountant", period_id="2026-10")
    bill1 = c.bills.get(bill1["id"])

    # payment with provider timeout, reconciliation, replay
    ap_pay = c.request_approval("payment.release", bill1["id"], actor_role="treasury", requested_by="owner")
    c.approve(ap_pay["id"], approver="owner")
    first = c.execute(ap_pay["id"], actor="treasury")
    replay = c.execute(ap_pay["id"], actor="treasury")
    c.provider.mode = "timeout_after_accept"
    dispatch = c.dispatch_payments()
    c.provider.mode = "accept"
    reconciled = c.reconcile_payments()
    intent = c.payments.get(first.result["intent"])
    settle_event = c.provider.settle(intent["logical_op_id"])
    c.payments.ingest_event(settle_event, actor="webhook")
    duplicate = c.payments.ingest_event(settle_event, actor="webhook")

    # period 2
    valve_evidence = c.evidence.register_document(project_id=project["id"], kind="stored_material_evidence", title="Valves: bill of sale, insurance certificate, laydown photos", actor=owner)
    valve_rev = c.evidence.add_revision(document_id=valve_evidence["id"], content=b"synthetic stored-material evidence: valves", note="title, insurance, location", actor=owner)
    lot2 = c.bills.add_stored_material(commitment_id=commitment["id"], sov_line_id=line1, description="Valves, on site", eligible_amount="5000", evidence_hash=valve_rev["content_hash"], location="laydown yard", actor=owner)
    bill2 = c.bills.certify(commitment_id=commitment["id"], period_id="2026-10", installed=[{"sov_line_id": line1, "cumulative_installed": "45000"}], transfers=[{"lot_id": lot1["id"], "amount": "10000"}], actor=owner)
    bill2_approval = c.request_approval("bill.approve", bill2["id"], actor_role="accountant", requested_by="accountant")
    c.approve(bill2_approval["id"], approver=owner, approver_role="owner")
    c.post_bill(bill2["id"], actor="accountant", period_id="2026-10")
    bill2 = c.bills.get(bill2["id"])

    pending_change = c.commitments.propose_change(commitment["id"], amount="12000", reason="Pending alternative - not executed", sov_line_id=line1, actor=owner)
    forecast = c.forecast.project(project["id"])

    # prime billing and collection
    prime = c.receivables.certify(project_id=project["id"], period_id="2026-10", certified_cumulative="60000", retainage_rate="0.10", actor=owner)
    c.approve_and_execute("prime_bill.approve", prime["id"], actor_role="owner")
    # external sending is its own authority when the receivables domain governs it
    if c._core_owner("prime_bill.send") is not None:
        c.approve_and_execute("prime_bill.send", prime["id"], actor_role="owner")
    else:
        c.receivables.send(prime["id"], actor=owner)
    # ACH collection requires the customer's recorded debit mandate when mandates are supported
    if hasattr(c.receivables, "record_mandate"):
        mandate_doc = c.evidence.register_document(project_id=project["id"], kind="ach_mandate", title="Customer ACH debit authorization (synthetic)", actor=owner)
        mandate_rev = c.evidence.add_revision(document_id=mandate_doc["id"], content=b"synthetic ACH debit authorization", note="signed authorization", actor=owner)
        c.receivables.record_mandate(customer_id=customer["id"], mandate_ref="MANDATE-SIM-0001", evidence_hash=mandate_rev["content_hash"], actor=owner)
    collection = c.receivables.record_collection(prime_bill_id=prime["id"], period_id="2026-10", amount="54000", fee="5", provider_ref="ach_sim_rcv_0001", actor=owner)
    c.close_period("2026-10")
    late_return = c.receivables.record_return(collection_id=collection["id"], period_id="2026-11", reason="late return after close (simulated)", actor=owner)

    # stale approval: bill certified, then commitment changed before execution
    bill3 = c.bills.certify(commitment_id=commitment["id"], period_id="2026-11", installed=[{"sov_line_id": line1, "cumulative_installed": "50000"}], actor=owner)
    ap_bill3 = c.request_approval("bill.approve", bill3["id"], actor_role="owner")
    c.approve(ap_bill3["id"])
    c.approve_and_execute("change.execute", pending_change["id"], actor_role="owner")
    stale_result = None
    try:
        c.post_bill(bill3["id"], actor="accountant", period_id="2026-11")
    except Exception as exc:  # StaleApprovalError or ApprovalNotGranted
        stale_result = type(exc).__name__

    # Ricky abstains on stale evidence
    rev2 = c.evidence.add_revision(document_id=drawing["id"], content=b"drawing A rev 2 (synthetic)", note="revised after pricing", actor=owner)
    stale_commitment = c.commitments.create(project_id=project["id"], supplier_id=supplier["id"], title="Follow-on subcontract", sov_lines=[{"description": "Extra", "amount": "1000"}], estimate_id=estimate["id"], actor=owner)
    ricky_abstain = c.ricky.propose("commitment.execute", actor_role="pm", context={"commitment_id": stale_commitment["id"]})
    ricky_role = c.ricky.propose("payment.release", actor_role="estimator", context={"bill_id": bill2["id"]})

    bill1 = c.bills.get(bill1["id"])
    return {
        "project_id": project["id"],
        "commitment_id": commitment["id"],
        "executed_amount": c.commitments.get(commitment["id"])["executed_amount"],
        "sov": [s["amount"] for s in c.commitments.get(commitment["id"])["sov"]],
        "bill1": {k: bill1[k] for k in ("cumulative_gross", "cumulative_retainage", "amount_due", "status")},
        "bill2": {k: bill2[k] for k in ("cumulative_installed", "cumulative_stored", "cumulative_gross", "cumulative_retainage", "cumulative_net", "amount_due", "retainage_this_period", "stored_transferred_this_period", "status")},
        "payment": {"first_replayed": first.replayed, "replay_replayed": replay.replayed, "dispatch": dispatch, "reconciled": reconciled, "transfers": len(c.provider.transfers), "status": c.payments.get(intent["id"])["status"], "duplicate_event": duplicate},
        "forecast_before_change": forecast,
        "prime": {k: c.receivables.get(prime["id"])[k] for k in ("amount_due", "retainage_cumulative", "revenue_this_period", "status")},
        "collection": collection, "late_return": late_return,
        "stale_result": stale_result, "ap_bill3_status": c.approvals.get(ap_bill3["id"])["status"],
        "ricky_abstain": ricky_abstain, "ricky_role": ricky_role,
        "trial_balance": c.ledger.trial_balance(),
        "ap": c.bills.ap_open_items(project["id"]), "ar": c.receivables.ar_open_items(project["id"]),
        "bank": fmt(c.ledger.balance("1000")), "fees": fmt(c.ledger.balance("6000")), "cost": fmt(c.ledger.balance("5000")), "stored": fmt(c.ledger.balance("1300")),
        "audit": c.audit.verify_chain(),
        "lots": c.bills.lots(commitment["id"]),
    }
