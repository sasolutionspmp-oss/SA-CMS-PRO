"""Real JPEG/PNG decoding and immutable filesystem bytes; metadata/ACL fixtures only.

These host contracts do not qualify native Frappe persistence, HTTP or a scanner.
"""
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zlib

from PIL import Image

from cipher_aec.documents.core import DocumentService
from cipher_aec.documents.extraction import ArtifactError, MAX_BYTES, digest, extract_source, validate_source
from cipher_aec.documents.storage import LocalArtifactStorage
from cipher_aec.tests.test_documents import MemoryMetadata


def photo_bytes(kind="PNG", **options):
    output = io.BytesIO()
    Image.new("RGB", (8, 6), (41, 92, 137)).save(output, format=kind, **options)
    return output.getvalue()


def png_chunk(kind, content):
    return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xffffffff)


def png_pixels(width=1, height=1, compressed=None):
    return (b"\x89PNG\r\n\x1a\n" + png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + png_chunk(b"IDAT", compressed if compressed is not None else zlib.compress(b"\x00\x29\x5c\x89"))
            + png_chunk(b"IEND", b""))


class PhotoAdmissionTests(unittest.TestCase):
    def admit(self, content, filename):
        return validate_source(content, filename, len(content), digest(content))

    def test_real_jpeg_png_and_progressive_jpeg_have_truthful_empty_extraction(self):
        for content, filename, mime in ((photo_bytes(), "photo.PNG", "image/png"),
                (photo_bytes("JPEG"), "photo.jpg", "image/jpeg"),
                (photo_bytes("JPEG", progressive=True), "photo.jpeg", "image/jpeg")):
            with self.subTest(filename=filename):
                self.assertEqual(self.admit(content, filename), mime)
                extracted = extract_source(content, mime)
                self.assertEqual(extracted.status, "image_text_unavailable")
                self.assertEqual(extracted.pages, ("",))
                self.assertIn("No extracted text", extracted.warning)
                self.assertEqual(extracted.extractor_version, "cipher-safe-image-v1")

    def test_claimed_format_and_hash_size_mismatches_fail(self):
        png, jpeg = photo_bytes(), photo_bytes("JPEG")
        for content, filename in ((png, "photo.jpg"), (jpeg, "photo.png"), (b"not an image", "photo.png"),
                                  (png, "photo.svg"), (png, "photo.gif"), (png, "photo.txt")):
            with self.subTest(filename=filename), self.assertRaises(ArtifactError):
                self.admit(content, filename)
        with self.assertRaises(ArtifactError):
            validate_source(png, "photo.png", len(png), "0" * 64)
        with self.assertRaises(ArtifactError):
            validate_source(png, "photo.png", len(png) + 1, digest(png))
        with self.assertRaises(ArtifactError):
            self.admit(b"x" * (MAX_BYTES + 1), "photo.png")

    def test_truncated_corrupt_and_trailing_images_are_rejected(self):
        png, jpeg = photo_bytes(), photo_bytes("JPEG")
        for content, filename in ((png[:20], "photo.png"), (png[:-1], "photo.png"),
                (png + b"unrelated trailing bytes", "photo.png"),
                (png_pixels(compressed=b"not valid compressed pixels"), "photo.png"),
                (jpeg[:-2], "photo.jpg"), (jpeg + b"unrelated trailing bytes", "photo.jpg"),
                (b"\xff\xd8\xff\xe0\xff\xffbad\xff\xd9", "photo.jpg")):
            with self.subTest(filename=filename, length=len(content)), self.assertRaises(ArtifactError):
                self.admit(content, filename)

    def test_decoded_pixel_and_side_budgets_reject_tiny_compressed_bombs(self):
        for width, height in ((12001, 1), (1, 12001), (6000, 5000), (100000, 100000)):
            with self.subTest(width=width, height=height), self.assertRaises(ArtifactError):
                self.admit(png_pixels(width, height), "large.png")

    def test_animation_is_rejected_instead_of_admitting_only_first_frame(self):
        output = io.BytesIO()
        Image.new("RGB", (2, 2), "red").save(output, format="PNG", save_all=True,
            append_images=[Image.new("RGB", (2, 2), "blue")], duration=100, loop=0)
        with self.assertRaises(ArtifactError):
            self.admit(output.getvalue(), "animated.png")

    def test_decoder_timeout_failure_and_unavailable_fail_closed(self):
        png = photo_bytes()
        for failure in (subprocess.TimeoutExpired("decoder", 15), OSError("decoder unavailable")):
            with patch("cipher_aec.documents.extraction.subprocess.run", side_effect=failure), self.assertRaises(ArtifactError):
                self.admit(png, "photo.png")
        with patch("cipher_aec.documents.extraction.subprocess.run", return_value=subprocess.CompletedProcess([], 0, b"unexpected")), self.assertRaises(ArtifactError):
            self.admit(png, "photo.png")

    def test_preflight_only_skips_decode_and_core_admission_still_rejects_bad_pixels(self):
        invalid = png_pixels(compressed=b"not valid compressed pixels")
        with patch("cipher_aec.documents.extraction.subprocess.run") as worker:
            self.assertEqual(validate_source(invalid, "photo.png", len(invalid), digest(invalid), decode_images=False), "image/png")
            worker.assert_not_called()
        with self.assertRaises(ArtifactError):
            self.admit(invalid, "photo.png")

    def test_unsupported_mime_never_falls_through_to_pdf_parser(self):
        with patch("cipher_aec.documents.extraction.subprocess.run") as worker:
            self.assertEqual(extract_source(b"bad", "image/svg+xml").status, "unavailable")
            worker.assert_not_called()


class PhotoSourceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.repo = MemoryMetadata()
        self.storage = LocalArtifactStorage(self.directory.name)
        self.allowed = True
        def authorize(company, project, ability):
            if not self.allowed or company != "Synthetic Company" or project not in (None, "PROJECT-A"):
                raise PermissionError("Current exact source duty denied")
        self.project = DocumentService(self.repo, self.storage, authorize, allow_unscanned=True)
        self.company = DocumentService(self.repo, self.storage, authorize, scope_type="Company", allow_unscanned=True)

    def upload(self, service=None, content=None, filename="photo.png", **changes):
        service = service or self.project
        content = photo_bytes() if content is None else content
        values = dict(company="Synthetic Company", project=None if service is self.company else "PROJECT-A",
            title="Site photo", filename=filename, content=content, byte_length=len(content), sha256=digest(content))
        values.update(changes)
        return service.upload(**values)

    def test_company_and_project_original_bytes_and_source_pins_are_exact_after_restart(self):
        for service in (self.project, self.company):
            for kind, filename in (("PNG", "site.png"), ("JPEG", "site.jpeg")):
                content = photo_bytes(kind)
                saved = self.upload(service, content, filename)
                rid = saved["revision"]["id"]
                self.assertEqual(saved["revision"]["retrieval_status"], "available")
                self.assertEqual(saved["revision"]["page_count"], 1)
                self.assertEqual(json.loads(self.repo.revs[rid]["pages_json"]), [""])
                source = service.source_reference("Synthetic Company", None if service is self.company else "PROJECT-A", rid, 1, lock=True)
                self.assertEqual(source["content"], content)
                self.assertEqual(source["source_sha256"], digest(content))
                self.assertEqual(source["byte_length"], len(content))
                self.assertTrue(source["is_current"])
                revision, downloaded = service.download("Synthetic Company", rid)
                self.assertEqual(downloaded, content)
                self.assertEqual(LocalArtifactStorage(self.directory.name).read(revision["storage_reference"], digest(content), len(content)), content)

    def test_photo_has_no_excerpt_citation_text_preview_or_text_search_hit(self):
        for service in (self.project, self.company):
            saved = self.upload(service)
            rid = saved["revision"]["id"]
            for read in (lambda: service.citation("Synthetic Company", rid, 1), lambda: service.preview("Synthetic Company", rid, 1)):
                with self.assertRaisesRegex(ArtifactError, "OCR and image interpretation"):
                    read()
            self.assertEqual(service.search("Synthetic Company", None if service is self.company else "PROJECT-A", "Site photo"), [])

    def test_photo_successor_retains_exact_historical_revision_and_current_standing(self):
        first = self.upload()
        content = photo_bytes("JPEG")
        second = self.upload(content=content, filename="replacement.jpg", document_id=first["document"]["id"], expected_revision=1)
        old = self.project.source_reference("Synthetic Company", "PROJECT-A", first["revision"]["id"], 1, lock=True)
        current = self.project.source_reference("Synthetic Company", "PROJECT-A", second["revision"]["id"], 1, lock=True)
        self.assertFalse(old["is_current"])
        self.assertTrue(current["is_current"])
        self.assertEqual(old["current_revision"], current["revision_id"])
        self.assertEqual(current["content"], content)
        with self.assertRaises(ArtifactError):
            self.project.source_reference("Synthetic Company", "PROJECT-A", first["revision"]["id"], 2)

    def test_current_scope_revocation_precedes_image_bytes_after_prior_access(self):
        for service in (self.project, self.company):
            self.allowed = True
            saved = self.upload(service)
            rid = saved["revision"]["id"]
            service.download("Synthetic Company", rid)
            self.allowed = False
            for read in (lambda: service.download("Synthetic Company", rid),
                    lambda: service.source_reference("Synthetic Company", None if service is self.company else "PROJECT-A", rid, 1, lock=True)):
                with patch.object(self.storage, "read", wraps=self.storage.read) as content:
                    with self.assertRaises(PermissionError):
                        read()
                    content.assert_not_called()

    def test_wrong_company_scope_producer_rights_and_scan_policy_do_not_grant_image_bytes(self):
        saved = self.upload()
        rid = saved["revision"]["id"]
        for read in (lambda: self.project.download("Other Company", rid), lambda: self.company.download("Synthetic Company", rid)):
            with patch.object(self.storage, "read", wraps=self.storage.read) as content:
                with self.assertRaises(ArtifactError):
                    read()
                content.assert_not_called()
        def denied(row, lock=False):
            raise PermissionError("Current source rights denied")
        self.project.source_authorize = denied
        with patch.object(self.storage, "read", wraps=self.storage.read) as content:
            with self.assertRaises(PermissionError):
                self.project.download("Synthetic Company", rid)
            content.assert_not_called()
        self.project.source_authorize = None
        self.project.allow_unscanned = False
        with self.assertRaisesRegex(ArtifactError, "quarantined"):
            self.project.download("Synthetic Company", rid)

    def test_scanner_infected_and_default_unscanned_photo_remain_quarantined(self):
        self.project.allow_unscanned = False
        first = self.upload()
        self.assertEqual(first["revision"]["retrieval_status"], "quarantined")
        self.project.scanner = type("ScannerFixture", (), {"scan": lambda self, content, mime: "infected"})()
        second = self.upload()
        self.assertEqual(second["revision"]["extraction_status"], "blocked")
        for saved in (first, second):
            with self.assertRaisesRegex(ArtifactError, "quarantined"):
                self.project.download("Synthetic Company", saved["revision"]["id"])

    def test_malformed_photo_never_creates_metadata_or_stored_original(self):
        with self.assertRaises(ArtifactError):
            self.upload(content=png_pixels(compressed=b"not image pixels"))
        self.assertEqual(self.repo.docs, {})
        self.assertEqual(self.repo.revs, {})
        self.assertEqual(list(Path(self.directory.name).iterdir()), [])

    def test_upload_denial_precedes_expensive_image_decode(self):
        self.allowed = False
        with patch("cipher_aec.documents.extraction.subprocess.run") as worker:
            with self.assertRaises(PermissionError):
                self.upload()
            worker.assert_not_called()
        self.assertEqual(self.repo.docs, {})

    def test_changed_or_missing_photo_bytes_fail_source_pin_and_download(self):
        saved = self.upload()
        rid = saved["revision"]["id"]
        path = Path(self.directory.name) / rid
        for mutate in (lambda: path.write_bytes(b"altered"), lambda: path.unlink()):
            mutate()
            for read in (lambda: self.project.download("Synthetic Company", rid),
                    lambda: self.project.source_reference("Synthetic Company", "PROJECT-A", rid, 1)):
                with self.assertRaises(ArtifactError):
                    read()


if __name__ == "__main__":
    unittest.main()
