"""Read-only plans: never merge by a display name or apply an external import."""
from dataclasses import dataclass
from .validation import manifest_digest, manifest_requirements, parse_manifest, quantity_previews


@dataclass(frozen=True)
class TargetSnapshot:
    fields: dict
    version: str
    authority: str = "native"
    warnings: tuple[str, ...] = ()
    identity_matches: bool = True
    revision_matches: bool = True


def preview_manifest(value, reader):
    manifest = parse_manifest(value)
    results = []
    for row in manifest["records"]:
        target = row.get("target")
        if not target:
            results.append({"id": row["id"], "kind": row["kind"], "action": "create_candidate",
                            "reason": "No target identity is bound; no name matching or write was performed."})
            continue
        snapshot = reader(row, manifest)
        if snapshot is None:
            # A denied, wrong-scope and missing target produce exactly the same read model.
            results.append({"id": row["id"], "kind": row["kind"], "action": "unavailable",
                            "reason": "The target is not available in your current scope."})
            continue
        if not snapshot.identity_matches:
            results.append({"id": row["id"], "kind": row["kind"], "action": "identity_conflict",
                            "reason": "The source UUID does not match the registered immutable native unit identity."})
            continue
        if not snapshot.revision_matches:
            results.append({"id": row["id"], "kind": row["kind"], "action": "stale_unit_revision",
                            "reason": "The source unit revision does not match the registered native unit revision."})
            continue
        if target.get("version") and target["version"] != snapshot.version:
            results.append({"id": row["id"], "kind": row["kind"], "action": "stale",
                            "reason": "The accessible target version changed; refresh this preview."})
            continue
        if snapshot.authority == "operator_declaration_required":
            results.append({"id": row["id"], "kind": row["kind"], "action": "declaration_candidate",
                            "target_version": snapshot.version, "warnings": list(snapshot.warnings),
                            "reason": "Native UOM dimension and precision are unregistered; proposed declarations are not verified native authority.",
                            "proposed_declaration": {key: row["fields"][key] for key in ("dimension", "precision")}})
            continue
        changes = [{"field": key, "current": snapshot.fields.get(key), "proposed": proposed}
                   for key, proposed in row["fields"].items() if snapshot.fields.get(key) != proposed]
        action = "immutable_unit_conflict" if changes and snapshot.authority == "registered_unit" else "update_candidate" if changes else "matches"
        result = {"id": row["id"], "kind": row["kind"], "action": action,
                  "target_version": snapshot.version, "changes": changes}
        if snapshot.warnings:
            result["warnings"] = list(snapshot.warnings)
        if action == "immutable_unit_conflict":
            result["reason"] = "Registered unit metadata is immutable; this preview cannot authorize changing it."
        results.append(result)
    return {"schema": "cipher.canonical.preview.v1", "manifest_sha256": manifest_digest(manifest),
            "records": results, "quantity_previews": quantity_previews(manifest),
            "apply_available": False, "apply_unavailable_reason": "Source-specific business-data onboarding is deferred to MIG-02 (R4).",
            "writes_performed": 0, "setup_requirements": manifest_requirements(manifest)}
