"""Payment rails require verified practice workspaces and initialized simulators."""
import os
import shutil
import tempfile
import unittest
from unittest import mock

from apps.cipher.core.db import WorkspaceModeError
from apps.cipher.domain import payments as payment_module
from apps.cipher.domain.payments import ReleaseQuarantined, SimulatedProvider, sign_event
from apps.cipher.service import Cipher
from apps.cipher.tests.test_payments_controls import World, file_world, restored_copy
from apps.cipher.tests.test_workspace_mode import legacy_file


class UntrustedProvider:
    """A duck provider's own synthetic flags grant no payment authority."""

    synthetic = True
    live = False
    mode = "accept"

    def __init__(self):
        self.calls = []

    @property
    def webhook_secret(self):
        self.calls.append("secret")
        return "untrusted-provider-secret"

    def fee_for(self, amount):
        self.calls.append("fee")
        return "0.00"

    def submit(self, **kwargs):
        self.calls.append("submit")
        return {"outcome": "rejected", "reason": "untrusted rail"}

    def lookup(self, logical_op_id):
        self.calls.append("lookup")
        return {"found": False}

    def list_transfers(self):
        self.calls.append("list")
        return []


class ObservedSimulator(SimulatedProvider):
    """Record rail calls while retaining the initialized synthetic implementation."""

    def __init__(self):
        super().__init__()
        self.calls = []

    def fee_for(self, amount):
        self.calls.append("fee")
        return super().fee_for(amount)

    def submit(self, **kwargs):
        self.calls.append("submit")
        return super().submit(**kwargs)

    def lookup(self, logical_op_id):
        self.calls.append("lookup")
        return super().lookup(logical_op_id)

    def list_transfers(self):
        self.calls.append("list")
        return super().list_transfers()


class PaymentProviderIsolationTests(unittest.TestCase):
    def world(self):
        w = World()
        self.addCleanup(w.c.db.close)
        return w

    def queued(self, w):
        return w.release(w.posted_bill("20000")["id"])

    def test_a_duck_provider_is_refused_before_a_workspace_is_created(self):
        with tempfile.TemporaryDirectory(prefix="cipher-provider-mode-") as directory:
            path = os.path.join(directory, "practice.sqlite")
            untrusted = UntrustedProvider()
            with self.assertRaises(PermissionError):
                Cipher(path, provider=untrusted)
            self.assertEqual(untrusted.calls, [])
            self.assertEqual(os.listdir(directory), [])

    def test_attachment_rejects_duck_provider_before_reading_its_secret(self):
        w = self.world()
        original = w.c.payments.provider
        untrusted = UntrustedProvider()
        with self.assertRaises(PermissionError):
            w.c.payments.attach_provider(untrusted)
        self.assertEqual(untrusted.calls, [])
        self.assertIs(w.c.payments.provider, original)

    def test_a_duck_class_identity_property_is_not_read_during_provider_validation(self):
        class IdentitySpoof(UntrustedProvider):
            @property
            def __class__(self):
                self.calls.append("class identity")
                return SimulatedProvider

        untrusted = IdentitySpoof()
        with self.assertRaises(PermissionError):
            payment_module.Payments.require_simulated_provider(untrusted)
        self.assertEqual(untrusted.calls, [])

    def test_an_explicit_fee_quote_rejects_an_untrusted_provider_without_calling_it(self):
        w = self.world()
        untrusted = UntrustedProvider()
        with self.assertRaises(PermissionError):
            w.c.payments.fee_for("20000", untrusted)
        self.assertEqual(untrusted.calls, [])

    def test_dispatch_rejects_an_untrusted_provider_before_claiming_a_queued_payment(self):
        w = self.world()
        intent = self.queued(w)
        untrusted = UntrustedProvider()
        with self.assertRaises(PermissionError):
            w.c.payments.dispatch_pending(untrusted, actor="treasury-worker")
        self.assertEqual(untrusted.calls, [])
        self.assertEqual(w.c.payments.get(intent["id"])["status"], "queued")
        self.assertEqual(w.c.commands.get(intent["outbox_id"])["status"], "pending")
        self.assertEqual(len(w.c.provider.submissions), 0)

    def test_reconciliation_rejects_an_untrusted_provider_before_lookup_or_financial_changes(self):
        w = self.world()
        intent = self.queued(w)
        w.c.provider.mode = "timeout_after_accept"
        w.c.dispatch_payments()
        before = w.c.ledger.trial_balance()["journal_count"]
        untrusted = UntrustedProvider()
        with self.assertRaises(PermissionError):
            w.c.payments.reconcile(untrusted, actor="reconciler")
        self.assertEqual(untrusted.calls, [])
        self.assertEqual(w.c.payments.get(intent["id"])["status"], "outcome_unknown")
        self.assertEqual(w.c.ledger.trial_balance()["journal_count"], before)

    def test_post_construction_provider_replacement_is_refused(self):
        w = self.world()
        original = w.c.payments.provider
        untrusted = UntrustedProvider()
        with self.assertRaises(PermissionError):
            w.c.payments.provider = untrusted
        self.assertEqual(untrusted.calls, [])
        self.assertIs(w.c.payments.provider, original)

    def test_an_unregistered_callback_secret_cannot_replace_simulator_authority(self):
        w = self.world()
        original_provider = w.c.payments.provider
        original_secret = w.c.payments.webhook_secret
        with self.assertRaises(PermissionError):
            w.c.payments.webhook_secret = "third-party-callback-secret"
        self.assertIs(w.c.payments.provider, original_provider)
        self.assertEqual(w.c.payments.webhook_secret, original_secret)

    def test_secret_registry_replacement_cannot_bind_a_duck_provider_or_read_its_properties(self):
        w = self.world()
        original_provider = w.c.payments.provider
        original_secret = w.c.payments.webhook_secret
        untrusted = UntrustedProvider()
        with mock.patch.dict(payment_module._PROVIDERS, {"poisoned-secret": untrusted}):
            with self.assertRaises(PermissionError):
                w.c.payments.webhook_secret = "poisoned-secret"
        self.assertEqual(untrusted.calls, [])
        self.assertIs(w.c.payments.provider, original_provider)
        self.assertEqual(w.c.payments.webhook_secret, original_secret)

    def test_a_raw_callback_secret_replacement_cannot_authorize_a_foreign_signed_event(self):
        w = self.world()
        intent = self.queued(w)
        w.c.dispatch_payments()
        event = w.c.provider.settle(intent["logical_op_id"])
        foreign_secret = "third-party-callback-secret"
        w.c.payments._webhook_secret = foreign_secret
        foreign_event = sign_event(event, foreign_secret)
        before = w.c.ledger.trial_balance()["journal_count"]
        with self.assertRaises(PermissionError):
            w.c.payments.ingest_event(foreign_event, actor="provider-webhook")
        self.assertEqual(w.c.payments.get(intent["id"])["status"], "accepted")
        self.assertEqual(w.c.ledger.trial_balance()["journal_count"], before)

    def test_an_uninitialized_simulator_subclass_cannot_impersonate_a_bound_simulator(self):
        class UninitializedSimulator(SimulatedProvider):
            def __init__(self):
                self.webhook_secret = "unregistered-simulator"
                self.transfers = {}
                self.submissions = []

        w = self.world()
        with self.assertRaises(PermissionError):
            w.c.payments.attach_provider(UninitializedSimulator())

    def test_raw_binding_replacement_cannot_hide_an_untrusted_cancel_lookup(self):
        w = self.world()
        intent = self.queued(w)
        untrusted = UntrustedProvider()
        w.c.payments._provider = untrusted  # simulate a bypass of the public binding property
        with self.assertRaises(PermissionError):
            w.c.payments.cancel_intent(intent["id"], "synthetic protective cancellation", "treasury")
        self.assertEqual(untrusted.calls, [])
        self.assertEqual(w.c.payments.get(intent["id"])["status"], "queued")

    def test_recovery_rejects_an_untrusted_transfer_lister_before_any_provider_method(self):
        w = self.world()
        untrusted = UntrustedProvider()
        with self.assertRaises(PermissionError):
            w.c.payments.complete_recovery_reconciliation(untrusted, actor="reconciler")
        self.assertEqual(untrusted.calls, [])

    def test_raw_binding_replacement_cannot_authorize_a_signed_webhook(self):
        w = self.world()
        intent = self.queued(w)
        w.c.dispatch_payments()
        event = w.c.provider.settle(intent["logical_op_id"])
        before = w.c.ledger.trial_balance()["journal_count"]
        untrusted = UntrustedProvider()
        w.c.payments._provider = untrusted
        with self.assertRaises(PermissionError):
            w.c.payments.ingest_event(event, actor="provider-webhook")
        self.assertEqual(untrusted.calls, [])
        self.assertEqual(w.c.payments.get(intent["id"])["status"], "accepted")
        self.assertEqual(w.c.ledger.trial_balance()["journal_count"], before)

    def test_an_initialized_simulator_subclass_keeps_the_synthetic_dispatch_path(self):
        class SerializedProbe(SimulatedProvider):
            def submit(self, **kwargs):
                return super().submit(**kwargs)

        w = self.world()
        intent = self.queued(w)
        simulator = SerializedProbe()
        w.c.payments.attach_provider(simulator)
        self.assertEqual([r["status"] for r in w.c.payments.dispatch_pending(simulator, actor="worker")], ["accepted"])
        self.assertEqual(len(simulator.submissions), 1)
        self.assertEqual(w.c.payments.get(intent["id"])["status"], "accepted")


class PaymentWorkspaceModeTests(unittest.TestCase):
    def world(self):
        w = World(provider=ObservedSimulator())
        self.addCleanup(w.c.db.close)
        return w

    @staticmethod
    def effects(db):
        # Read the raw records so refusal tests do not rely on a service reader
        # admitting a workspace whose mode proof has deliberately been damaged.
        return {table: tuple(tuple(row) for row in db.conn.execute(f"SELECT * FROM {table} ORDER BY rowid"))
                for table in ("audit_log", "idempotency", "outbox", "payment_intents", "journals", "journal_lines")}

    @staticmethod
    def change_mode(db, mode):
        # Simulate direct SQL outside the application's guarded connection. The
        # internal scope is test-only and ends before any payment API is called.
        with db._internal() as raw:
            raw.execute("DROP TRIGGER workspace_mode_immutable")
            raw.execute("DROP TRIGGER workspace_mode_declaration_required")
            raw.execute("UPDATE workspace SET mode=?, mode_declaration_seq=CASE WHEN ? IS NULL THEN NULL ELSE mode_declaration_seq END WHERE id=1", (mode, mode))

    def test_changed_or_erased_mode_blocks_all_rail_seams_before_calls_or_writes(self):
        for mode in ("live", None):
            with self.subTest(mode=mode):
                w = self.world()
                intent = w.release(w.posted_bill("20000")["id"])
                self.change_mode(w.c.db, mode)
                before = self.effects(w.c.db)
                simulator = w.c.provider
                simulator.calls.clear()
                original_secret = w.c.payments.webhook_secret
                replacement = SimulatedProvider()
                operations = {
                    "fee quote": lambda: w.c.payments.fee_for("20000"),
                    "dispatch": lambda: w.c.payments.dispatch_pending(simulator, actor="worker"),
                    "reconcile": lambda: w.c.payments.reconcile(simulator, actor="reconciler"),
                    "recovery": lambda: w.c.payments.complete_recovery_reconciliation(simulator, actor="reconciler"),
                    "cancel": lambda: w.c.payments.cancel_intent(intent["id"], "synthetic cancellation", "treasury"),
                    "adoption": lambda: w.c.payments.manifest_for("payment.adopt_transfer", "sim_000001", actor_role="owner"),
                    "attachment": lambda: w.c.payments.attach_provider(replacement),
                    "secret binding": lambda: setattr(w.c.payments, "webhook_secret", replacement.webhook_secret),
                    "provider binding": lambda: setattr(w.c.payments, "provider", replacement),
                }
                for seam, operation in operations.items():
                    with self.subTest(seam=seam), self.assertRaises(WorkspaceModeError):
                        operation()
                    self.assertEqual(simulator.calls, [], seam)
                    self.assertEqual(self.effects(w.c.db), before, seam)
                    self.assertIs(w.c.payments.provider, simulator, seam)
                    self.assertEqual(w.c.payments.webhook_secret, original_secret, seam)
                self.assertEqual(len(simulator.submissions), 0)

    def test_a_signed_settlement_cannot_write_after_the_mode_changes_on_the_same_connection(self):
        w = self.world()
        intent = w.release(w.posted_bill("20000")["id"])
        w.c.dispatch_payments()
        event = w.c.provider.settle(intent["logical_op_id"])
        self.change_mode(w.c.db, "live")
        before = self.effects(w.c.db)
        w.c.provider.calls.clear()
        with self.assertRaises(WorkspaceModeError):
            w.c.payments.ingest_event(event, actor="provider-webhook")
        self.assertEqual(w.c.provider.calls, [])
        self.assertEqual(self.effects(w.c.db), before)
        self.assertEqual(w.c.db.conn.execute("SELECT status FROM payment_intents WHERE id=?", (intent["id"],)).fetchone()[0], "accepted")

    def test_a_deleted_workspace_refuses_a_provider_call_before_financial_effects(self):
        w = self.world()
        with w.c.db._internal() as raw:
            raw.execute("DROP TRIGGER workspace_no_delete")
            raw.execute("DELETE FROM workspace WHERE id=1")
        before = self.effects(w.c.db)
        w.c.provider.calls.clear()
        with self.assertRaises(WorkspaceModeError):
            w.c.payments.fee_for("20000")
        self.assertEqual(w.c.provider.calls, [])
        self.assertEqual(self.effects(w.c.db), before)

    def test_a_declared_practice_copy_can_bind_its_simulator_without_acquiring_write_authority(self):
        w, directory = file_world(self, provider=ObservedSimulator())
        intent = w.release(w.posted_bill("20000")["id"])
        copy = restored_copy(self, w, w.c.snapshot(os.path.join(directory, "practice-copy.sqlite")))
        self.assertEqual(copy.db.require_practice_mode()["mode"], "practice")
        self.assertFalse(copy.db.mode_status()["runtime_authorized"])
        self.assertFalse(copy.db.has_write_authority())
        copy.payments.attach_provider(w.c.provider)
        self.assertEqual(copy.payments.fee_for("20000"), "0.00")
        before = self.effects(copy.db)
        w.c.provider.calls.clear()
        with self.assertRaises(ReleaseQuarantined):
            copy.payments.dispatch_pending(w.c.provider, actor="worker")
        self.assertEqual(w.c.provider.calls, [])
        self.assertEqual(self.effects(copy.db), before)
        self.assertEqual(copy.payments.get(intent["id"])["status"], "queued")

    def test_a_known_legacy_copy_can_bind_for_diagnostics_but_cannot_call_the_rail(self):
        with tempfile.TemporaryDirectory(prefix="cipher-payment-mode-") as directory:
            source = os.path.join(directory, "legacy.sqlite")
            path = os.path.join(directory, "legacy-copy.sqlite")
            legacy_file(source)
            shutil.copy2(source, path)
            simulator = ObservedSimulator()
            copy = Cipher.open_restored(path, provider=simulator)
            self.addCleanup(copy.db.close)
            status = copy.db.mode_status()
            self.assertEqual((status["mode"], status["verified"], status["runtime_authorized"]), (None, False, False))
            self.assertIs(copy.payments.provider, simulator)
            self.assertEqual(simulator.calls, [])
            before = self.effects(copy.db)
            operations = (
                lambda: copy.payments.fee_for("20000"),
                lambda: copy.payments.dispatch_pending(simulator, actor="worker"),
                lambda: copy.payments.reconcile(simulator, actor="reconciler"),
                lambda: copy.payments.complete_recovery_reconciliation(simulator, actor="reconciler"),
                lambda: copy.payments.ingest_event({}, actor="provider-webhook"),
            )
            for operation in operations:
                with self.assertRaises(WorkspaceModeError):
                    operation()
                self.assertEqual(simulator.calls, [])
                self.assertEqual(self.effects(copy.db), before)


if __name__ == "__main__":
    unittest.main()
