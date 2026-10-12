"""Browser workflow check.

Starts the console on an ephemeral port with the golden fixture seeded, then
drives the console's own JavaScript self-test (``/?selftest=1``) in headless
Chrome/Chromium and records the outcome.  The self-test exercises the real
UI code path (fetch -> JSON API -> service): approval refusal before grant,
execution, bill certification, Ricky proposal, payment release with timeout,
reconciliation, duplicate-event handling and reconciliation checks.

Usage:  python -m apps.cipher.tools.browser_check [--out evidence.json] [--chrome PATH]
Exit code 0 on pass, 1 on fail, 2 if no browser is available (the API-only
fallback still runs and is reported).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request

from ..server import BackgroundServer
from ..service import Cipher, run_golden_fixture

CHROME_CANDIDATES = [
    os.environ.get("CIPHER_CHROME", ""),
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
]


def find_browser(explicit: str | None = None) -> str | None:
    for cand in ([explicit] if explicit else []) + CHROME_CANDIDATES:
        if cand and os.path.exists(cand):
            return cand
    for name in ("google-chrome", "chromium", "chromium-browser", "chrome", "msedge"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _get_json(url: str, token: str | None) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"} if token else {})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _summary(state: dict) -> dict:
    return {
        "project": (state.get("project") or {}).get("name"),
        "trial_balance_balanced": (state.get("trial_balance") or {"balanced": True})["balanced"],
        "audit_chain_ok": (state.get("audit_chain") or {"ok": True})["ok"],
        "approvals": len(state.get("approvals") or []),
    }


def _drive(base_url: str, token: str | None, chrome: str | None, evidence: dict) -> int:
    evidence["target"] = base_url
    evidence["api_only"] = _summary(_get_json(base_url + "/api/state", token))
    browser = find_browser(chrome)
    if browser is None:
        evidence["browser"] = {"available": False}
        return 2
    nonce = f"run{int(time.time() * 1000):x}"
    start = f"{base_url}/?selftest={nonce}" + (f"&token={token}" if token else "")
    profile = tempfile.mkdtemp(prefix="cipher-chrome-")
    cmd = [
        browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--no-default-browser-check",
        "--disable-extensions", f"--user-data-dir={profile}", start,
    ]
    report: dict = {"result": None}
    proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        # The page posts its outcome (tagged with this run's nonce) to the server; poll for it.
        deadline = time.time() + 120
        while time.time() < deadline:
            try:
                report = _get_json(base_url + "/api/selftest", token)
            except Exception:
                report = {"result": None}
            if report.get("result") and report.get("nonce") == nonce:
                break
            if proc.poll() is not None:
                break
            time.sleep(0.5)
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        shutil.rmtree(profile, ignore_errors=True)
    matched = report.get("nonce") == nonce
    evidence["browser"] = {
        "available": True,
        "browser": browser,
        "result": (report.get("result") if matched else None) or "no-result",
        "steps": report.get("steps", []) if matched else [],
        "user_agent": report.get("user_agent", ""),
    }
    evidence["after"] = _summary(_get_json(base_url + "/api/state", token))
    ok = evidence["browser"]["result"] == "pass" and evidence["after"]["trial_balance_balanced"] and evidence["after"]["audit_chain_ok"]
    return 0 if ok else 1


def run(out_path: str | None, chrome: str | None, url: str | None = None, token: str | None = None) -> int:
    evidence: dict = {"api_only": {}, "browser": None}
    if url:
        code = _drive(url.rstrip("/"), token, chrome, evidence)
    else:
        cipher = Cipher()
        run_golden_fixture(cipher)
        with BackgroundServer(cipher) as server:
            code = _drive(server.url, None, chrome, evidence)
    _write(out_path, evidence)
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return code


def _write(out_path: str | None, evidence: dict) -> None:
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(evidence, fh, indent=2, ensure_ascii=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--chrome", default=None)
    ap.add_argument("--url", default=None, help="drive an already-running console (e.g. the container) instead of an in-process one")
    ap.add_argument("--token", default=os.environ.get("CIPHER_TOKEN"), help="access token for --url (default: CIPHER_TOKEN)")
    args = ap.parse_args(argv)
    return run(args.out, args.chrome, url=args.url, token=args.token)


if __name__ == "__main__":
    sys.exit(main())
