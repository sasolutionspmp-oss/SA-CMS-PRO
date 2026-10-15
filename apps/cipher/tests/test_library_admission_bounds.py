"""Bounded actual76/77 admission checks without source/future-tail coupling."""
import unittest
from unittest.mock import patch
from apps.cipher.service import Cipher
from apps.cipher.domain import library
from apps.cipher import library_receipts


class LibraryAdmissionBoundsTests(unittest.TestCase):
    def checks(self,c):
        return ((library,c.plugin('library')._installed,library.SCHEMA_NAME,library.LibraryError),
                (library_receipts,library_receipts.LibraryReceipts(c.db,c.audit)._installed,library_receipts.SCHEMA_NAME,library_receipts.LibraryReceiptError))

    def test_maximum_sqlite_integer_never_requests_version_sized_allocation(self):
        c=Cipher(':memory:');self.addCleanup(c.db.close)
        for module,check,name,error in self.checks(c):
            with self.subTest(schema=name):
                version=c.db.scalar('SELECT version FROM schema_version WHERE name=?',(name,))
                c.db.execute('UPDATE schema_version SET version=? WHERE name=?',(2**63-1,name))
                before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
                def bounded_range(*args):
                    if len(args)>1 and args[1]>1000:self.fail('Untrusted migration number sized an allocation')
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
                c.db.execute('UPDATE schema_version SET version=? WHERE name=?',(-(2**63),name))
                before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
                try:
                    with self.assertRaises(error):check()
                    self.assertEqual((tuple(c.db.conn.iterdump()),c.db.conn.total_changes),before)
                finally:c.db.execute('UPDATE schema_version SET version=? WHERE name=?',(version,name))

    def test_lost_receipt77_keeps_native76_but_refuses_api77(self):
        c=Cipher(':memory:');self.addCleanup(c.db.close)
        c.db.execute('DELETE FROM schema_version WHERE name=?',(library_receipts.SCHEMA_NAME,))
        self.assertTrue(c.plugin('library')._installed())
        with self.assertRaises(library_receipts.LibraryReceiptError):library_receipts.LibraryReceipts(c.db,c.audit)._installed()

    def test_missing_earlier_dependency_holds_both_named_admissions(self):
        c=Cipher(':memory:');self.addCleanup(c.db.close)
        c.db.execute("DELETE FROM schema_version WHERE name='foundation'")
        before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
        for module,check,name,error in self.checks(c):
            with self.subTest(schema=name),self.assertRaises(error):check()
        self.assertEqual((tuple(c.db.conn.iterdump()),c.db.conn.total_changes),before)

    def test_nonpositive_prefix_row_cannot_compensate_for_missing_positive_dependency(self):
        c=Cipher(':memory:');self.addCleanup(c.db.close)
        c.db.execute("UPDATE schema_version SET version=0 WHERE name='foundation'")
        before=tuple(c.db.conn.iterdump()),c.db.conn.total_changes
        for module,check,name,error in self.checks(c):
            with self.subTest(schema=name),self.assertRaises(error):check()
        self.assertEqual((tuple(c.db.conn.iterdump()),c.db.conn.total_changes),before)
