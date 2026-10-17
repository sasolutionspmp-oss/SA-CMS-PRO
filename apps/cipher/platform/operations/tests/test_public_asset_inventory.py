"""Public assets must be complete inputs to a frozen application build."""
import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "public_asset_recorder", Path(__file__).resolve().parents[1] / "record-evidence.py"
)
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)
PREFIX = "apps/cipher/product/public/"


class PublicAssetInventoryTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.public = self.root / PREFIX
        self.public.mkdir(parents=True)
        for name, data in {
            "cipher-mark.svg": b'<svg xmlns="http://www.w3.org/2000/svg"/>',
            "THIRD_PARTY_NOTICES.txt": b"Dependency notices",
        }.items():
            (self.public / name).write_bytes(data)
        for name, value in (("ROOT", self.root), ("CIPHER", self.root / "apps/cipher")):
            manager = patch.object(recorder, name, value)
            manager.start()
            self.addCleanup(manager.stop)

    def test_every_authored_public_file_is_hashed_regardless_of_extension(self):
        for name in ("font.woff2", "nested/no-extension", ".well-known/asset"):
            target = self.public / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"\x00\xff authored asset")
        expected = {
            str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in self.public.rglob("*") if p.is_file()
        }
        self.assertEqual(recorder.sources(), expected)

    def test_missing_either_original_refuses_incomplete_snapshot(self):
        for name in ("cipher-mark.svg", "THIRD_PARTY_NOTICES.txt"):
            with self.subTest(name=name):
                path = self.public / name
                data = path.read_bytes()
                path.unlink()
                with self.assertRaises(ValueError):
                    recorder.sources()
                path.write_bytes(data)

    def test_authored_symlinks_cannot_be_silently_omitted(self):
        (self.public / "alias.svg").symlink_to(self.public / "cipher-mark.svg")
        with self.assertRaises(ValueError):
            recorder.sources()

    def test_only_generated_pdfjs_directory_is_excluded(self):
        generated = self.public / "pdfjs/maps/generated.json"
        generated.parent.mkdir(parents=True)
        generated.write_text('{"derived":true}')
        authored = self.public / "pdfjs-custom.json"
        authored.write_text('{"authored":true}')
        selected = recorder.sources()
        self.assertNotIn(PREFIX + "pdfjs/maps/generated.json", selected)
        self.assertEqual(selected[PREFIX + "pdfjs-custom.json"], hashlib.sha256(authored.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
