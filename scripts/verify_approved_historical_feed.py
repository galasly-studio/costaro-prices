#!/usr/bin/env python3
"""Verify a human-approved historical catalog for a ONE-TIME Pages feed.

This script never changes the research prices.json, any active rate, or the
GitHub material publication policy. It creates only a separately staged copy.
The audit date remains 2026-08-30: no claim of November price verification.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from stage_initial_historical_catalog import stage
from validate_app_catalog import load, validate


HISTORICAL_AUDIT_DATE = "2026-08-30"
APPROVED_VERSION = "0.1.1"


def verify(research, embedded, policy, approved, manifest, readiness,
           *, approved_bytes: bytes) -> dict:
    """Fail closed unless the candidate exactly matches approved baseline."""
    if not isinstance(manifest, dict) or not isinstance(readiness, dict):
        raise ValueError("Missing approval manifest or staging report")

    digest = hashlib.sha256(approved_bytes).hexdigest().upper()
    if manifest.get("sha256") != digest:
        raise ValueError("Approved catalog SHA-256 does not match manifest")
    for field, expected in {
        "status": "approved_historical_fallback",
        "decision": "option_1",
        "catalogVersion": APPROVED_VERSION,
        "historicalAuditDate": HISTORICAL_AUDIT_DATE,
        "currentMarketPricesVerified": False,
        "publishedToGitHub": False,
        "publishedToGooglePlay": False,
        "workingCatalogUnchanged": True,
    }.items():
        if type(manifest.get(field)) is not type(expected) or manifest[field] != expected:
            raise ValueError("Approval manifest mismatch: " + field)

    if readiness.get("status") != "historical_fallback_staged_for_manual_review":
        raise ValueError("Original preparation was not safely staged")
    if readiness.get("historicalAuditDate") != HISTORICAL_AUDIT_DATE:
        raise ValueError("Historical audit date changed in preparation")
    if readiness.get("catalogVersionCandidate") != APPROVED_VERSION:
        raise ValueError("Approved candidate version changed")
    for key in ("priceValuesChanged", "auditDateChanged",
                "currentMarketPricesVerified", "automaticPublicationApproved",
                "publishedCatalogModified"):
        if readiness.get(key) is not False:
            raise ValueError("Unsafe preparation flag: " + key)

    prepared_report, expected_catalog = stage(
        research, embedded, policy,
        acknowledged_audit_date=HISTORICAL_AUDIT_DATE,
    )
    if approved != expected_catalog:
        raise ValueError("Approved catalog differs from exact historical baseline")
    if validate(approved, embedded):
        raise ValueError("Approved catalog fails application schema checks")
    if prepared_report["catalogVersionCandidate"] != APPROVED_VERSION:
        raise ValueError("Unexpected generated historical version")

    return {
        "schemaVersion": 1,
        "status": "historical_feed_verified_for_manual_deployment",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "catalogVersion": APPROVED_VERSION,
        "sourceAuditDate": HISTORICAL_AUDIT_DATE,
        "sha256": digest,
        "materialRates": len(approved["materialPrices"]),
        "laborRates": len(approved["laborPrices"]),
        "currentMarketPricesVerified": False,
        "researchCatalogChanged": False,
        "automaticPricePublicationApproved": False,
        "requiresExplicitManualGitHubDeployment": True,
    }


def _write_new(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--research", type=Path, default=Path("prices.json"))
    parser.add_argument("--baseline", type=Path, default=Path("app_embedded_baseline.json"))
    parser.add_argument("--policy", type=Path, default=Path("material_update_policy.json"))
    parser.add_argument("--approved", type=Path,
                        default=Path("published_catalog/prices.json"))
    parser.add_argument("--manifest", type=Path,
                        default=Path("published_catalog/approval_manifest.json"))
    parser.add_argument("--readiness", type=Path,
                        default=Path("published_catalog/readiness.json"))
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    inputs = {p.resolve() for p in (
        args.research, args.baseline, args.policy, args.approved,
        args.manifest, args.readiness,
    )}
    targets = {args.candidate.resolve(), args.report.resolve()}
    if len(targets) != 2 or inputs & targets:
        raise ValueError("Staging outputs cannot overwrite source files")
    if args.candidate.exists() or args.report.exists():
        raise FileExistsError("Staging target already exists; overwrite refused")

    approved_bytes = args.approved.read_bytes()
    report = verify(
        load(args.research), load(args.baseline), load(args.policy),
        json.loads(approved_bytes.decode("utf-8-sig")),
        load(args.manifest), load(args.readiness),
        approved_bytes=approved_bytes,
    )
    _write_new(args.candidate, json.loads(approved_bytes.decode("utf-8-sig")))
    _write_new(args.report, report)
    print("COSTARO HISTORICAL FEED VERIFIED FOR SEPARATE MANUAL DEPLOYMENT")
    print("Version:", report["catalogVersion"])
    print("Original audit date:", report["sourceAuditDate"])
    print("Market prices reverified:", report["currentMarketPricesVerified"])
    print("Active research catalog and policies were NOT changed")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"COSTARO HISTORICAL FEED BLOCKED: {error}", file=sys.stderr)
        raise SystemExit(2) from error
