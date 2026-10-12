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


def run(out_path: str | None, chrome: str | None) -> int:
    cipher = Cipher()
    run_golden_fixture(cipher)
    evidence = {"api_only": {}, "browser": None}
    with BackgroundServer(cipher) as server:
        # API-only sanity (always runs)
        with urllib.request.urlopen(server.url + "/api/state", timeout=10) as r:
            state = json.loads(r.read())
        evidence["api_only"] = {
            "project": state["project"]["name"],
            "trial_balance_balanced": state["trial_balance"]["balanced"],
            "audit_chain_ok": state["audit_chain"]["ok"],
            "approvals": len(state["approvals"]),
        }
        browser = find_browser(chrome)
        if browser is None:
            evidence["browser"] = {"available": False}
            _write(out_path, evidence)
            print(json.dumps(evidence, indent=2))
            return 2
        profile = tempfile.mkdtemp(prefix="cipher-chrome-")
        cmd = [
            browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run", "--no-default-browser-check",
            "--disable-extensions", f"--user-data-dir={profile}", server.url + "/?selftest=1",
        ]
        report = {"result": None}
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            # The page posts its outcome to /api/selftest when the journey finishes; poll for it.
            deadline = time.time() + 90
            while time.time() < deadline:
                try:
                    with urllib.request.urlopen(server.url + "/api/selftest", timeout=5) as r:
                        report = json.loads(r.read())
                except Exception:
                    report = {"result": None}
                if report.get("result"):
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
        evidence["browser"] = {
            "available": True,
            "browser": browser,
            "result": report.get("result") or "no-result",
            "steps": report.get("steps", []),
            "user_agent": report.get("user_agent", ""),
        }
        # the state after the journey is also checked server-side
        with urllib.request.urlopen(server.url + "/api/state", timeout=10) as r:
            state = json.loads(r.read())
        evidence["after"] = {"trial_balance_balanced": state["trial_balance"]["balanced"], "audit_chain_ok": state["audit_chain"]["ok"], "audit_entries": state["audit_chain"].get("entries")}
    _write(out_path, evidence)
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    return 0 if evidence["browser"]["result"] == "pass" and evidence["after"]["trial_balance_balanced"] else 1


def _write(out_path: str | None, evidence: dict) -> None:
    if out_path:
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(evidence, fh, indent=2, ensure_ascii=False)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--chrome", default=None)
    args = ap.parse_args(argv)
    return run(args.out, args.chrome)


if __name__ == "__main__":
    sys.exit(main())
