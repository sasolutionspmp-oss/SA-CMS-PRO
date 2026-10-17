import unittest
import uuid
from datetime import datetime, timezone

from cipher_aec.api.contracts import canonical_json, digest, expected_version, money, operation_id, text, utc_timestamp, version_of
from cipher_aec.api.paging import decode_cursor, encode_cursor, page_options
from cipher_aec.api.errors import DomainError


class ContractTests(unittest.TestCase):
    def test_money_requires_exact_decimal_string(self):
        self.assertEqual(money("23456.78"), {"amount": "23456.78", "currency": "USD"})
        self.assertEqual(money("-1.00", "USD")["amount"], "-1.00")
        for value in (1.1, 10, True, None, "NaN", "1e2", "01.00", "+1.00", "1.0", "-0.00", "10000000000000.00"):
            with self.subTest(value=value), self.assertRaises(DomainError):
                money(value)

    def test_currency_rejects_untrusted_format(self):
        for value in ("usd", "US", "USD\n", 1):
            with self.subTest(value=value), self.assertRaises(DomainError):
                money("1.00", value)

    def test_uuid_is_canonical_version_four(self):
        value = str(uuid.uuid4())
        self.assertEqual(operation_id(value), value)
        for invalid in (value.upper(), str(uuid.uuid1()), "123", None):
            with self.subTest(value=invalid), self.assertRaises(DomainError):
                operation_id(invalid)

    def test_canonical_hash_is_order_independent_and_payload_sensitive(self):
        self.assertEqual(digest({"b": 2, "a": 1}), digest({"a": 1, "b": 2}))
        self.assertNotEqual(digest({"a": 1}), digest({"a": 2}))
        with self.assertRaises(ValueError):
            canonical_json({"amount": float("nan")})

    def test_missing_version_has_428(self):
        with self.assertRaises(DomainError) as result:
            expected_version(None)
        self.assertEqual(result.exception.status, 428)

    def test_version_preserves_microseconds(self):
        self.assertEqual(version_of({"modified": datetime(2026, 10, 15, 5, 1, 2, 123)}), "2026-10-15 05:01:02.000123")

    def test_timestamp_is_utc(self):
        self.assertEqual(utc_timestamp(datetime(2026, 10, 15, tzinfo=timezone.utc)), "2026-10-15T00:00:00Z")

    def test_persisted_site_timestamp_is_converted_with_actual_offset_and_dst(self):
        self.assertEqual(utc_timestamp(datetime(2026, 10, 15, 20, 12, 34), source_timezone="Asia/Kolkata"), "2026-10-15T14:42:34Z")
        self.assertEqual(utc_timestamp(datetime(2026, 7, 15, 9), source_timezone="America/New_York"), "2026-07-15T13:00:00Z")
        self.assertEqual(utc_timestamp(datetime(2026, 1, 15, 9), source_timezone="America/New_York"), "2026-01-15T14:00:00Z")
        self.assertEqual(utc_timestamp(datetime(2026, 10, 15, tzinfo=timezone.utc), source_timezone="Asia/Kolkata"), "2026-10-15T00:00:00Z")

    def test_bounded_paging_and_text(self):
        self.assertEqual(page_options("50"), (50, None, "none"))
        self.assertEqual(page_options(200, count_mode="exact"), (200, None, "exact"))
        for limit in (0, 201, True, "2.5"):
            with self.subTest(limit=limit), self.assertRaises(DomainError):
                page_options(limit)
        self.assertEqual(text("  Task  ", "Subject"), "Task")
        with self.assertRaises(DomainError):
            text("a\x00b", "Subject")

    def test_cursor_is_signed_scoped_and_expiring(self):
        scope = {"company": "A", "user": "Morgan", "collection": "tasks"}
        token = encode_cursor(secret="test-secret", scope=scope, last=["2026-10-15 00:00:00", "TASK-1"], now=100)
        self.assertEqual(decode_cursor(token, secret="test-secret", scope=scope, now=101)[1], "TASK-1")
        for candidate, key, candidate_scope, now in ((token + "a", "test-secret", scope, 101),
                (token, "other-secret", scope, 101), (token, "test-secret", {**scope, "company": "B"}, 101),
                (token, "test-secret", scope, 1001)):
            with self.subTest(candidate=candidate, scope=candidate_scope, now=now), self.assertRaises(DomainError):
                decode_cursor(candidate, secret=key, scope=candidate_scope, now=now)


if __name__ == "__main__":
    unittest.main()
