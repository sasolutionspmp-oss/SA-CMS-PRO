"""Literal independent fixture process adapter; no SMTP/HTTP/provider exists."""
import base64
import json
import subprocess
import sys

from cipher_aec.api.contracts import canonical_json
from cipher_aec.api.errors import DomainError
from .distribution import sink_path


def _call(request):
    result = subprocess.run([sys.executable, "-m", "cipher_aec.integrations.distribution_sink", sink_path()],
        input=canonical_json(request), text=True, capture_output=True, timeout=20, check=False)
    if result.returncode:
        raise DomainError("fixture_sink_unavailable", "The independent fixture sink cannot confirm this outcome.", 503)
    try:
        return json.loads(result.stdout)["receipt"]
    except (ValueError, KeyError):
        raise DomainError("fixture_sink_unavailable", "The independent fixture sink returned no verifiable acknowledgment.", 503) from None


def readback(logical_key):
    return _call({"operation": "readback", "logical_key": logical_key})


def accept(logical_key, payload, content, attempt_not_after):
    return _call({"operation": "accept", "logical_key": logical_key, "payload": payload,
        "content_base64": base64.b64encode(content).decode("ascii"), "attempt_not_after": attempt_not_after})
