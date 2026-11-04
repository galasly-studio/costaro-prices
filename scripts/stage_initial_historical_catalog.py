#!/usr/bin/env python3
"""Stage a one-time historical COSTARO fallback catalog; NEVER publish it.

This is the *manual bootstrap* step, not a monthly price update. It preserves
all historical prices, work rates, package sizes and the original audit date.
The generated candidate is for a separate human-reviewed promotion only.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import sys

from validate_app_catalog import load, validate, version_valid


def stage(catalog, baseline, policy, *, acknowledged_audit_date: str):
    """Return (readiness, staged catalog); never mutate input values."""
    errors = validate(catalog, baseline)
    if errors:
        raise ValueError("Current catalog is invalid: " + "; ".join(errors))
    if catalog != baseline:
        raise ValueError("Initial bootstrap requires the exact frozen app baseline")
    if catalog.get("status") != "draft" or catalog.get("automaticUpdatesEnabled") is not False:
        raise ValueError("Only the original disabled draft can be bootstrapped")
    if (not isinstance(policy, dict) or policy.get("schemaVersion") != 1
            or policy.get("enabled") is not False
            or policy.get("automaticPublicationApproved") is True
            or policy.get("approvedMappings") != []):
        raise ValueError("Material publication policy must remain fully disabled")

    audit_date = catalog.get("sourceAuditDate")
    if not isinstance(audit_date, str) or acknowledged_audit_date != audit_date:
        raise ValueError("Historical audit date must be explicitly acknowledged")
    try:
        parsed_date = date.fromisoformat(audit_date)
    except ValueError as error:
        raise ValueError("Invalid historical audit date") from error
    if parsed_date > date.today():
        raise ValueError("Historical audit date cannot be in the future")

    version = catalog.get("catalogVersion")
    if not version_valid(version):
        raise ValueError("Invalid catalog version")
    major, minor, patch = (int(part) for part in version.split("."))
    if patch >= 999999:
        raise ValueError("Catalog version patch exhausted")

    candidate = deepcopy(catalog)
    candidate["catalogVersion"] = f"{major}.{minor}.{patch + 1}"
    candidate["status"] = "published"
    candidate["automaticUpdatesEnabled"] = True
    errors = validate(candidate, baseline)
    if errors:
        raise ValueError("Staged catalog is incompatible: " + "; ".join(errors))

    expected = deepcopy(catalog)
    for name in ("catalogVersion", "status", "automaticUpdatesEnabled"):
        expected[name] = candidate[name]
    if candidate != expected:
        raise AssertionError("Unexpected changes to prices or metadata")

    report = {
        "schemaVersion": 1,
        "status": "historical_fallback_staged_for_manual_review",
        "historicalAuditDate": audit_date,
        "catalogVersionBefore": version,
        "catalogVersionCandidate": candidate["catalogVersion"],
        "materialKeys": len(candidate["materialPrices"]),
        "laborKeys": len(candidate["laborPrices"]),
        "priceValuesChanged": False,
        "auditDateChanged": False,
        "currentMarketPricesVerified": False,
        "automaticPublicationApproved": False,
        "publishedCatalogModified": False,
        "requiresSeparateManualPromotion": True,
    }
    return report, candidate


def _write_new(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--baseline", type=Path, default=Path("app_embedded_baseline.json"))
    parser.add_argument("--policy", type=Path, default=Path("material_update_policy.json"))
    parser.add_argument("--acknowledge-historical-audit-date", required=True)
    parser.add_argument("--candidate", type=Path,
                        default=Path("historical_baseline_candidate/prices.json"))
    parser.add_argument("--report", type=Path,
                        default=Path("historical_baseline_readiness.json"))
    args = parser.parse_args(argv)

    inputs = {p.resolve() for p in (args.catalog, args.baseline, args.policy)}
    outputs = {args.candidate.resolve(), args.report.resolve()}
    if len(outputs) != 2 or outputs & inputs:
        raise ValueError("Output paths must be distinct and must not overwrite inputs")
    if args.candidate.exists() or args.report.exists():
        raise FileExistsError("Historical approval outputs already exist; no overwrite")

    report, candidate = stage(
        load(args.catalog), load(args.baseline), load(args.policy),
        acknowledged_audit_date=args.acknowledge_historical_audit_date,
    )
    _write_new(args.candidate, candidate)
    _write_new(args.report, report)
    print("HISTORICAL FALLBACK STAGED FOR REVIEW (NOT PUBLISHED)")
    print("Unchanged source audit date:", report["historicalAuditDate"])
    print("Catalog candidate:", args.candidate)
    print("Readiness report:", args.report)
    print("Live prices.json and material_update_policy.json were NOT changed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError) as error:
        print(f"COSTARO HISTORICAL BASELINE ERROR: {error}", file=sys.stderr)
        raise SystemExit(2) from error
