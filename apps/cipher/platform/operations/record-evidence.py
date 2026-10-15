#!/usr/bin/env python3
"""Record source/artifact hashes without upgrading test evidence into a release claim."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
CIPHER = ROOT / "apps/cipher"
EXCLUDED = {"node_modules", "dist", "test-results", "playwright-report", "__pycache__", ".pytest_cache", ".git", ".venv"}
SOURCE_SUFFIXES = {".py", ".json", ".ts", ".tsx", ".css", ".html", ".mjs", ".yml", ".yaml", ".sh", ".toml", ".txt", ".md", ".in", ".conf"}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sources() -> dict[str, str]:
    found = {}
    for directory in (CIPHER / "platform", CIPHER / "product"):
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            relative = path.relative_to(ROOT)
            if any(part in EXCLUDED or part.endswith(".egg-info") for part in relative.parts):
                continue
            if path.suffix not in SOURCE_SUFFIXES or path.name.startswith("."):
                continue
            found[str(relative)] = sha(path)
    return found


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=CIPHER / "docs/framework/evidence/EVIDENCE_INDEX.json")
    args = parser.parse_args()
    current = sources()
    artifacts = []
    evidence_dir = CIPHER / "docs/framework/evidence"
    for path in sorted(evidence_dir.rglob("*")):
        if not path.is_file() or path.resolve() == args.output.resolve() or path.suffix not in {".json", ".md", ".png"}:
            continue
        item = {"path": str(path.relative_to(ROOT)), "sha256": sha(path), "bytes": path.stat().st_size}
        if path.suffix == ".json":
            data = json.loads(path.read_text())
            if isinstance(data, dict) and isinstance(data.get("source_sha256"), dict):
                changed, missing, matched = [], [], 0
                for name, recorded in data["source_sha256"].items():
                    # Reports use explicit repository paths for app and workflow sources;
                    # older backend-local paths retain their original fixed base.
                    candidate = ROOT / name if name.startswith(("apps/", ".github/")) else CIPHER / "platform/apps/cipher_aec/cipher_aec" / name
                    if not candidate.is_file():
                        missing.append(name)
                    elif sha(candidate) != recorded:
                        changed.append(name)
                    else:
                        matched += 1
                item["recorded_sources"] = {"matched": matched, "changed_since_capture": changed, "missing": missing}
        artifacts.append(item)
    manifest_hash = hashlib.sha256(json.dumps(current, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    result = {
        "schema_version": 1,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "git_revision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "git_revision_context": "Repository HEAD at capture; source_sha256 identifies the actual working source, including uncommitted implementation.",
        "source_tree_sha256": manifest_hash,
        "source_sha256": current,
        "artifacts": artifacts,
        "qualification": "Hash inventory only. Historical evidence remains bound to its captured source; changed files require relevant revalidation before a new release claim.",
        "live_model_qualified": False,
        "live_accounting_qualified": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"source_files": len(current), "evidence_artifacts": len(artifacts), "manifest": str(args.output), "source_tree_sha256": manifest_hash}))


if __name__ == "__main__":
    main()
