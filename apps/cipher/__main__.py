"""Command line: ``python -m apps.cipher <command>``.

  serve   [--db PATH] [--port N] [--demo]   run the owner console
  practice-web [--port N]                   run the read-only Fluent practice app
  ap-practice-web [--port N]                run the disposable Fluent AP workflow
  commercial-practice-web [--port N]        run the disposable manual estimating workflow
  ar-practice-web [--port N]                run the disposable owner billing workflow
  library-practice-web [--port N]           run the disposable authored library workflow
  rfi-practice-web [--port N]               run the disposable RFI workflow
  demo    [--db PATH]                        run the golden fixture and print the summary
  test                                       run the test suite
  export  [--db PATH] [--out FILE]           write the audit export
  schema  [--db PATH]                        print schema lifecycle status
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unittest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cipher", description="Cipher synthetic prototype")
    sub = parser.add_subparsers(dest="command", required=True)

    s = sub.add_parser("serve", help="run the owner console")
    s.add_argument("--db", default=os.environ.get("CIPHER_DB", "data/cipher.sqlite"))
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=int(os.environ.get("CIPHER_PORT", "8765")))
    s.add_argument("--demo", action="store_true", help="seed the golden fixture when the workspace is empty")
    s.add_argument("--token", default=None, help="access token (default: CIPHER_TOKEN); required for non-loopback hosts")

    d = sub.add_parser("demo", help="run the golden fixture")
    d.add_argument("--db", default=":memory:")

    sub.add_parser("test", help="run the test suite")

    pw = sub.add_parser("practice-web", help="run the Fluent app against a fresh read-only synthetic workspace")
    pw.add_argument("--port", type=int, default=8766)

    apw = sub.add_parser("ap-practice-web", help="run the Fluent AP workflow in a fresh synthetic workspace")
    apw.add_argument("--port", type=int, default=8767)

    cw = sub.add_parser("commercial-practice-web", help="run the Fluent manual estimating workflow in a fresh synthetic workspace")
    cw.add_argument("--port", type=int, default=8768)

    arw = sub.add_parser("ar-practice-web", help="run the Fluent owner billing workflow in a fresh synthetic workspace")
    arw.add_argument("--port", type=int, default=8769)

    lw = sub.add_parser("library-practice-web", help="run the Fluent authored library workflow in a fresh synthetic workspace")
    lw.add_argument("--port", type=int, default=8770)

    rfw = sub.add_parser("rfi-practice-web", help="run the Fluent RFI workflow in a fresh synthetic workspace")
    rfw.add_argument("--port", type=int, default=8771)

    e = sub.add_parser("export", help="write the audit export")
    e.add_argument("--db", default=os.environ.get("CIPHER_DB", "data/cipher.sqlite"))
    e.add_argument("--out", default="-")

    sc = sub.add_parser("schema", help="schema lifecycle status")
    sc.add_argument("--db", default=os.environ.get("CIPHER_DB", "data/cipher.sqlite"))

    ch = sub.add_parser("claim-challenge", help="show this workspace copy's claim challenge")
    ch.add_argument("--db", required=True)

    cc = sub.add_parser("claim-code", help="compute this copy's claim code from CIPHER_OWNER_SECRET (run where the secret lives)")
    cc.add_argument("--db", required=True)

    cl = sub.add_parser("claim", help="claim write authority for a restored or copied workspace")
    cl.add_argument("--db", required=True)
    cl.add_argument("--approver", required=True)
    cl.add_argument("--reason", required=True)
    cl.add_argument("--code", default=None, help="owner claim code (required when CIPHER_OWNER_SECRET is set)")

    args = parser.parse_args(argv)

    if args.command == "practice-web":
        from .practice_server import serve_practice
        try:
            serve_practice(port=args.port)
        except (OSError, ValueError) as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "ap-practice-web":
        from .ap_practice_server import serve_ap_practice
        try:
            serve_ap_practice(port=args.port)
        except (OSError, ValueError) as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "commercial-practice-web":
        from .commercial_practice_server import serve_commercial_practice
        try:
            serve_commercial_practice(port=args.port)
        except (OSError, ValueError) as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "ar-practice-web":
        from .ar_practice_server import serve_ar_practice
        try:
            serve_ar_practice(port=args.port)
        except (OSError, ValueError) as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "library-practice-web":
        from .library_practice_server import serve_library_practice
        try:
            serve_library_practice(port=args.port)
        except (OSError, ValueError) as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "rfi-practice-web":
        from .rfi_practice_server import serve_rfi_practice
        try:
            serve_rfi_practice(port=args.port)
        except (OSError, ValueError) as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "serve":
        from .server import InsecureBindError, serve
        if args.db != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(args.db)), exist_ok=True)
        try:
            serve(args.db, args.host, args.port, demo=args.demo, token=args.token)
        except InsecureBindError as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        return 0

    if args.command == "demo":
        from .service import Cipher, run_golden_fixture
        result = run_golden_fixture(Cipher(args.db))
        summary = {k: result[k] for k in ("executed_amount", "sov", "bill1", "bill2", "prime", "bank", "cost", "stored", "audit")}
        summary["payment"] = {k: result["payment"][k] for k in ("transfers", "status", "replay_replayed")}
        summary["forecast"] = {k: result["forecast_before_change"][k] for k in ("budget", "executed_commitments", "pending_exposure", "forecast_at_completion", "variance_to_budget")}
        summary["ap_reconciled"] = result["ap"]["reconciled"]
        summary["ar_reconciled"] = result["ar"]["reconciled"]
        summary["trial_balance_balanced"] = result["trial_balance"]["balanced"]
        print(json.dumps(summary, indent=2, default=str))
        return 0

    if args.command == "test":
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.dirname(os.path.dirname(here))
        suite = unittest.defaultTestLoader.discover(os.path.join(here, "tests"), top_level_dir=root)
        result = unittest.TextTestRunner(verbosity=1).run(suite)
        return 0 if result.wasSuccessful() else 1

    if args.command == "export":
        from .service import Cipher
        export = Cipher(args.db).audit_export()
        text = json.dumps(export, indent=2, default=str)
        if args.out == "-":
            print(text)
        else:
            with open(args.out, "w", encoding="utf-8") as fh:
                fh.write(text)
            print(f"wrote {args.out}")
        return 0

    if args.command == "schema":
        # The service registers the complete catalog before existing-file checks.
        from .service import Database
        from .core.db import SchemaError
        db = None
        try:
            db = Database(args.db)
            db.require_practice_mode(allow_pending=True)
            print(json.dumps(db.schema_status(), indent=2))
        except SchemaError as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 2
        finally:
            if db is not None:
                db.close()
        return 0

    if args.command in ("claim-challenge", "claim-code", "claim"):
        from .core.db import WriteAuthorityError
        from .service import Cipher
        if not os.path.exists(args.db):
            print(f"cipher: no workspace at {args.db}", file=sys.stderr)
            return 2
        c = Cipher(args.db)
        ws = c.db.workspace()
        if args.command == "claim-challenge":
            print(json.dumps({"workspace_id": ws["workspace_id"], "authority_epoch": ws["authority_epoch"], "challenge": c.db.claim_challenge(),
                              "effective_write_authority": c.db.has_write_authority()}, indent=2))
            return 0
        if args.command == "claim-code":
            secret = os.environ.get("CIPHER_OWNER_SECRET")
            if not secret:
                print("cipher: CIPHER_OWNER_SECRET is not set", file=sys.stderr)
                return 2
            print(c.db.expected_claim_code(secret))
            return 0
        try:
            status = c.claim_write_authority(actor=args.approver, reason=args.reason, claim_code=args.code)
        except WriteAuthorityError as exc:
            print(f"cipher: {exc}", file=sys.stderr)
            return 1
        print(json.dumps(status, indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
