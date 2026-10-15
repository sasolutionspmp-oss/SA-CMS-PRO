"""Concurrent test processes retain their own temporary workspaces."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest


class ParallelTestWorkspaceTests(unittest.TestCase):
    def test_import_keeps_an_aged_active_peer_root_and_cleans_only_its_own(self):
        repository = Path(__file__).resolve().parents[3]
        with tempfile.TemporaryDirectory(prefix="parallel-test-harness-") as base:
            env = {**os.environ, "TMPDIR": base, "TMP": base, "TEMP": base}
            code = (
                "import sys; from pathlib import Path; import apps.cipher.tests as harness; "
                "root=Path(harness._root); (root/'active.txt').write_text('synthetic active test'); "
                "print(root, flush=True); sys.stdin.readline(); "
                "assert (root/'active.txt').exists(), 'another test import removed an active workspace'"
            )
            peer = subprocess.Popen([sys.executable, "-c", code], cwd=repository, env=env,
                                    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                active = Path(peer.stdout.readline().strip())
                self.assertEqual(active.parent, Path(base))
                aged = time.time() - 120
                os.utime(active, (aged, aged))
                other = subprocess.run([sys.executable, "-c",
                    "import apps.cipher.tests as harness; print(harness._root)"],
                    cwd=repository, env=env, text=True, capture_output=True, timeout=15)
                self.assertEqual(other.returncode, 0, other.stderr)
                self.assertTrue((active / "active.txt").exists(),
                                "a new test run deleted another live run merely because its root was old")
                self.assertFalse(Path(other.stdout.strip()).exists(), "the exited run must clean its own root")
                stdout, stderr = peer.communicate("\n", timeout=15)
                self.assertEqual(peer.returncode, 0, stderr)
                self.assertFalse(active.exists(), "the original run must clean its own root on exit")
            finally:
                if peer.poll() is None:
                    peer.communicate("\n", timeout=15)


if __name__ == "__main__":
    unittest.main()
