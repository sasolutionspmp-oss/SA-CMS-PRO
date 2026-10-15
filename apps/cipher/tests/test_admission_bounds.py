"""Actual named admissions fail closed with bounded work and independent tails."""
import copy
import unittest
from unittest.mock import patch

from apps.cipher.service import Cipher
from apps.cipher.domain import commercial,owner_billing
from apps.cipher import ar_receipts
from apps.cipher.commercial_practice_fixture import make_commercial_practice_fixture

SQLITE_MAX=2**63-1
SQLITE_MIN=-(2**63)


class AdmissionBoundsTests(unittest.TestCase):
    def checks(self,c):
        return ((commercial,c.plugin('commercial')._schema_installed,commercial.SCHEMA_NAME,commercial.CommercialError),
                (owner_billing,c.plugin('owner_billing')._schema_installed,owner_billing.SCHEMA_NAME,owner_billing.OwnerBillingError),
                (ar_receipts,ar_receipts.ARReceipts(c.db,c.audit).verify_integrity,ar_receipts.SCHEMA_NAME,ar_receipts.ARReceiptError))

    def test_maximum_sqlite_integer_refuses_without_requesting_version_sized_allocation(self):
        # Intercept module-local range before allocation on the unfixed source.
        # The actual SQLite value is MAX INTEGER; a failing baseline is safe.
        c=Cipher(':memory:');self.addCleanup(c.db.close)
        for module,check,name,error in self.checks(c):
            with self.subTest(schema=name):
                version=c.db.scalar('SELECT version FROM schema_version WHERE name=?',(name,))
                c.db.execute('UPDATE schema_version SET version=? WHERE name=?',(SQLITE_MAX,name))
                before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
                def bounded_range(*args):
                    if len(args)>1 and args[1]>1000:
                        self.fail('Admission requested a range sized by untrusted migration number')
                    return range(*args)
                try:
                    with patch.object(module,'range',new=bounded_range,create=True),self.assertRaises(error):check()
                    self.assertEqual((tuple(c.db.conn.iterdump()),c.db.conn.total_changes),before)
                finally:c.db.execute('UPDATE schema_version SET version=? WHERE name=?',(version,name))

    def test_minimum_sqlite_integer_is_refused_without_writes(self):
        c=Cipher(':memory:');self.addCleanup(c.db.close)
        for module,check,name,error in self.checks(c):
            with self.subTest(schema=name):
                version=c.db.scalar('SELECT version FROM schema_version WHERE name=?',(name,))
                c.db.execute('UPDATE schema_version SET version=? WHERE name=?',(SQLITE_MIN,name))
                before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
                try:
                    with self.assertRaises(error):check()
                    self.assertEqual((tuple(c.db.conn.iterdump()),c.db.conn.total_changes),before)
                finally:c.db.execute('UPDATE schema_version SET version=? WHERE name=?',(version,name))

    def test_original_native_commercial_source_survives_later_ar_admission_hole(self):
        c=make_commercial_practice_fixture();self.addCleanup(c.db.close)
        domain=c.plugin('commercial');identifier=c.commercial_practice_records['current_estimate_id']
        original=copy.deepcopy(domain.source(identifier))
        c.db.execute('DELETE FROM schema_version WHERE name=?',(owner_billing.SCHEMA_NAME,))
        before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
        self.assertEqual(domain.source(identifier),original)
        with self.assertRaises(ar_receipts.ARReceiptError):ar_receipts.ARReceipts(c.db,c.audit).verify_integrity()
        self.assertEqual((tuple(c.db.conn.iterdump()),c.db.conn.total_changes),before)

    def test_missing_earlier_dependency_still_refuses_every_later_named_admission(self):
        c=Cipher(':memory:');self.addCleanup(c.db.close)
        c.db.execute("DELETE FROM schema_version WHERE name='foundation'")
        before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
        for module,check,name,error in self.checks(c):
            with self.subTest(schema=name),self.assertRaises(error):check()
        self.assertEqual((tuple(c.db.conn.iterdump()),c.db.conn.total_changes),before)
