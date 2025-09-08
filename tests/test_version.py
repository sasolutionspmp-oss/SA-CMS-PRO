from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sa_cms_pro import __version__  # noqa: E402


def test_version():
    assert __version__ == "1.0.0"  # nosec B101
