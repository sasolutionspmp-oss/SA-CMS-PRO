"""Command line: ``python -m apps.cipher <command>``.

  serve   [--db PATH] [--port N] [--demo]   run the owner console
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

    e = sub.add_parser("export", help="write the audit export")
    e.add_argument("--db", default=os.environ.get("CIPHER_DB", "data/cipher.sqlite"))
    e.add_argument("--out", default="-")

    sc = sub.add_parser("schema", help="schema lifecycle status")
    sc.add_argument("--db", default=os.environ.get("CIPHER_DB", "data/cipher.sqlite"))

    args = parser.parse_args(argv)

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
        from .core.db import Database
        print(json.dumps(Database(args.db).schema_status(), indent=2))
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
