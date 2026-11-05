#!/usr/bin/env python3
"""Build a *staged* COSTARO catalog only when every publication gate passes.

Never writes the published prices.json. A separate guarded GitHub workflow may
promote a staged file after tests, and only after human approval of SKU/tier
mappings and initial published-catalog bootstrap.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from plan_verified_material_updates import plan
from plan_verified_labor_updates import plan as plan_labor
from validate_app_catalog import load, validate, version_valid


def _prepare_material_only(catalog, baseline, sources, observations, policy, *, now=None):
    """Return (readiness report, optional release catalog); fail closed."""
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    planned, proposal = plan(catalog, baseline, sources, observations, policy, now=now)
    holds = []
    if catalog.get("status") != "published" or catalog.get("automaticUpdatesEnabled") is not True:
        holds.append("initial_catalog_is_not_published_and_verified")
    if policy.get("enabled") is not True:
        holds.append("approved_tier_mapping_policy_is_disabled")
    if policy.get("automaticPublicationApproved") is not True:
        holds.append("explicit_automatic_publication_approval_missing")
    if not policy.get("approvedMappings"):
        holds.append("no_human_approved_product_tier_mappings")
    if planned["proposedCount"] == 0:
        holds.append("no_fresh_safe_price_changes")

    changes = []
    for row in planned["materials"]:
        if row["status"] == "proposed":
            mapping = next(
                entry for entry in policy["approvedMappings"]
                if entry["observationId"] == row["observationId"]
            )
            changes.append({
                "observationId": row["observationId"],
                "catalogMaterialKey": row["catalogMaterialKey"],
                "tier": mapping["tier"],
                "oldMDL": row["previousMDL"],
                "newMDL": row["proposedMDL"],
            })

    candidate = None
    if not holds:
        candidate = deepcopy(proposal)
        previous_version = catalog.get("catalogVersion")
        if not version_valid(previous_version):
            raise ValueError("Invalid current catalog version")
        major, minor, patch = (int(part) for part in previous_version.split("."))
        if patch >= 999999:
            raise ValueError("Version patch exhausted; manual migration required")
        candidate["catalogVersion"] = f"{major}.{minor}.{patch + 1}"
        # sourceAuditDate describes the common audit date of the entire
        # catalog. A partial monthly price update must not misrepresent every
        # untouched material (or any labor price) as newly audited.
        # Keep the historical global date until a separate FULL catalog audit
        # is explicitly approved. The partial update date belongs in the
        # readiness report, not in a global app-facing freshness claim.
        candidate["sourceAuditDate"] = catalog["sourceAuditDate"]

        errors = validate(candidate, baseline)
        if errors:
            raise ValueError("Proposed release fails app validation: " + "; ".join(errors))

        # Assert the *only* allowed catalog modifications are these prices,
        # patch-version increase, and the audit date. Labor is immutable.
        expected = deepcopy(catalog)
        # Handle both scalar and packaged catalog prices without normalizing units.
        for change in changes:
            slot = expected["materialPrices"][change["catalogMaterialKey"]][change["tier"]]
            if isinstance(slot, dict):
                slot["price"] = change["newMDL"]
            else:
                expected["materialPrices"][change["catalogMaterialKey"]][change["tier"]] = change["newMDL"]
        expected["catalogVersion"] = candidate["catalogVersion"]
        expected["sourceAuditDate"] = candidate["sourceAuditDate"]
        if expected != candidate:
            raise ValueError("Unexpected fields changed in staged catalog")

    readiness = {
        "schemaVersion": 1,
        "status": "ready_for_guarded_publication" if candidate is not None else "held",
        "generatedAt": now.isoformat(),
        "catalogVersionBefore": catalog.get("catalogVersion"),
        "catalogVersionCandidate": candidate.get("catalogVersion") if candidate else None,
        "policyEnabled": policy.get("enabled") is True,
        "explicitPublicationApproved": policy.get("automaticPublicationApproved") is True,
        "proposedPriceChanges": planned["proposedCount"],
        "approvedMappingCount": len(policy.get("approvedMappings", [])),
        "holdReasons": holds,
        "changes": changes,
        "lastVerifiedPartialMaterialChangeDate": now.date().isoformat() if candidate else None,
        "globalCatalogAuditDatePreserved": True,
        "publishedCatalogUnchangedByPreparation": True,
    }
    return readiness, candidate


def prepare(catalog, baseline, sources, observations, policy, *, now=None,
            labor_policy=None, labor_evidence=None):
    """Stage independently approved material and/or labor changes, never write.

    Without both labor inputs, the established material-only contract remains
    unchanged for existing callers. Labor-only publication cannot bypass the
    independent labor policy; disabled material policy never authorizes labor.
    """
    report, material_candidate = _prepare_material_only(
        catalog, baseline, sources, observations, policy, now=now)
    if labor_policy is None and labor_evidence is None:
        return report, material_candidate
    if labor_policy is None or labor_evidence is None:
        raise ValueError("Labor policy and verified evidence must be supplied together")

    labor_report, labor_proposal = plan_labor(
        catalog, baseline, labor_policy, labor_evidence, now=now)
    labor_authorized = (
        catalog.get("status") == "published"
        and catalog.get("automaticUpdatesEnabled") is True
        and labor_policy.get("enabled") is True
        and labor_policy.get("automaticPublicationApproved") is True
        and labor_report["proposedCount"] > 0
    )
    report["laborProposedPriceChanges"] = labor_report["proposedCount"]
    report["laborApprovalEnabled"] = (
        labor_policy.get("enabled") is True
        and labor_policy.get("automaticPublicationApproved") is True)
    report["lastVerifiedPartialLaborChangeDate"] = None
    if not labor_authorized:
        return report, material_candidate

    # No labor price is ever copied from the research-only collector: only
    # individually validated records from the manually verified document.
    staged = deepcopy(material_candidate if material_candidate is not None else catalog)
    if material_candidate is None:
        previous_version = catalog.get("catalogVersion")
        if not version_valid(previous_version):
            raise ValueError("Invalid current catalog version")
        major, minor, patch = (int(part) for part in previous_version.split("."))
        if patch >= 999999:
            raise ValueError("Version patch exhausted; manual migration required")
        staged["catalogVersion"] = f"{major}.{minor}.{patch + 1}"

    labor_changes = []
    for row in labor_report["laborUpdates"]:
        if row["status"] != "proposed":
            continue
        key, tier = row["workKey"], row["tier"]
        group = "laborStagePrices" if key == "startPuttyWork" else "laborPrices"
        staged[group][key][tier] = labor_proposal[group][key][tier]
        labor_changes.append({
            "kind": "labor", "workKey": key, "tier": tier,
            "oldMDL": row["previousMDL"], "newMDL": row["proposedMDL"],
        })

    # A complete comparison rules out hidden edits to unrelated materials,
    # rates, package metadata, version or global historical audit date.
    expected = deepcopy(material_candidate if material_candidate is not None else catalog)
    expected["catalogVersion"] = staged["catalogVersion"]
    for change in labor_changes:
        group = "laborStagePrices" if change["workKey"] == "startPuttyWork" else "laborPrices"
        expected[group][change["workKey"]][change["tier"]] = change["newMDL"]
    if expected != staged:
        raise ValueError("Unexpected fields modified in guarded labor candidate")
    if staged["sourceAuditDate"] != catalog["sourceAuditDate"]:
        raise ValueError("Labor update must not rewrite global historical audit date")
    errors = validate(staged, baseline)
    if errors:
        raise ValueError("Labor release candidate fails validation: " + "; ".join(errors))

    report["status"] = "ready_for_guarded_publication"
    report["holdReasons"] = []
    report["catalogVersionCandidate"] = staged["catalogVersion"]
    report["proposedPriceChanges"] += len(labor_changes)
    report["changes"].extend(labor_changes)
    report["lastVerifiedPartialLaborChangeDate"] = (
        now or datetime.now(timezone.utc)).astimezone(timezone.utc).date().isoformat()
    return report, staged


def _write_new(path: Path, payload) -> None:
    """Refuse to overwrite an earlier candidate or a user's report."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    with path.open("x", encoding="utf-8") as stream:
        stream.write(serialized)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--baseline", type=Path, default=Path("app_embedded_baseline.json"))
    parser.add_argument("--sources", type=Path, default=Path("price_sources.json"))
    parser.add_argument("--observations", type=Path, default=Path("price_observations.json"))
    parser.add_argument("--policy", type=Path, default=Path("material_update_policy.json"))
    parser.add_argument("--labor-policy", type=Path)
    parser.add_argument("--labor-evidence", type=Path)
    parser.add_argument("--candidate", type=Path, default=Path("release_candidate/prices.json"))
    parser.add_argument("--report", type=Path, default=Path("verified_release_readiness.json"))
    args = parser.parse_args(argv)
    if args.catalog.resolve() in (args.candidate.resolve(), args.report.resolve()):
        raise ValueError("Preparation cannot overwrite current prices.json")
    if args.candidate.resolve() == args.report.resolve():
        raise ValueError("Candidate and report paths must be different")
    report, candidate = prepare(
        load(args.catalog), load(args.baseline),
        load(args.sources), load(args.observations), load(args.policy),
        labor_policy=load(args.labor_policy) if args.labor_policy else None,
        labor_evidence=load(args.labor_evidence) if args.labor_evidence else None)
    if args.report.exists() or args.candidate.exists():
        raise FileExistsError("Remove stale release outputs manually before retrying")
    if candidate is not None:
        _write_new(args.candidate, candidate)
        print("VERIFIED candidate staged (not published):", args.candidate)
    _write_new(args.report, report)
    print("=== COSTARO SAFE RELEASE GATE ===")
    print("Result:", report["status"])
    print("Price changes considered:", report["proposedPriceChanges"])
    print("Reasons held:", ", ".join(report["holdReasons"]) or "none")
    print("Current prices.json has NOT been changed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"COSTARO RELEASE GATE ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
