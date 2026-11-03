#!/usr/bin/env python3
"""Build a safe, exhaustive manual research queue for every COSTARO work.

Research leads contain NO prices. This script neither fetches websites nor
updates tiers, source benchmarks, app calculations or the published catalog.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlparse

from audit_labor_prices import LABOR_KEYS, catalog_errors, load, required_unit
from audit_live_labor_drift import _check_report, audit as audit_drift
from collect_live_labor_quotes import validate_rules


ALL_KEYS = (*LABOR_KEYS, "startPuttyWork")
RESEARCH_URLS = frozenset({
    "https://euroremontstyle.md/remont-kvartir-ceny",
    "https://topmaster.md/price/demontazh/",
    "https://tsgate.pereflex.md/en/catalog/floor%20install.html?brand%5B%5D=30&filter=1",
})
LEAD_FIELDS = frozenset({
    "workKey", "url", "label", "unit", "technology", "scopeLimitation",
    "accessNeedsVerification", "approvedForPublication",
})


def check_leads(document: dict, unmapped: set[str]) -> dict[str, list[dict]]:
    """No price fields, remote publishing permission or arbitrary URLs allowed."""
    if (not isinstance(document, dict)
            or set(document) != {
                "schemaVersion", "market", "currency", "researchOnly",
                "publicationAllowed", "description", "leads",
            }
            or document["schemaVersion"] != 1 or document["market"] != "MD"
            or document["currency"] != "MDL"
            or document["researchOnly"] is not True
            or document["publicationAllowed"] is not False
            or not isinstance(document["description"], str)
            or not isinstance(document["leads"], list)):
        raise ValueError("Unsafe manual labor leads schema")
    by_key: dict[str, list[dict]] = defaultdict(list)
    identities = set()
    for lead in document["leads"]:
        if not isinstance(lead, dict) or set(lead) != LEAD_FIELDS:
            raise ValueError("Unrecognized or price-bearing research lead")
        key, url = lead["workKey"], lead["url"]
        if key not in unmapped or url not in RESEARCH_URLS:
            raise ValueError("Lead must belong to an unmapped key and an approved research URL")
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.username or parsed.password
                or parsed.port not in (None, 443) or parsed.fragment):
            raise ValueError("Unsafe lead URL")
        if (lead["unit"] != required_unit(key)
                or not isinstance(lead["label"], str) or len(lead["label"]) < 14
                or not isinstance(lead["accessNeedsVerification"], bool)
                or lead["approvedForPublication"] is not False
                or not all(isinstance(lead[field], str) and
                           re.fullmatch(r"[a-z0-9_]+", lead[field])
                           for field in ("technology", "scopeLimitation"))):
            raise ValueError("Unsafe or incomplete manual lead")
        identity = key, url, lead["label"]
        if identity in identities:
            raise ValueError("Duplicate manual research lead")
        identities.add(identity)
        by_key[key].append(lead)
    if set(by_key) != unmapped:
        raise ValueError("All and only unmapped catalog keys must have manual leads")
    return by_key


def build_queue(catalog: dict, sources: dict, rules_doc: dict,
                live: dict, drift: dict, leads_doc: dict) -> dict:
    errors = catalog_errors(catalog)
    if errors:
        raise ValueError("Invalid catalog: " + "; ".join(errors))
    rules = validate_rules(rules_doc, sources)
    observations = _check_report(catalog, live)
    if (live.get("summary", {}).get("workTypesMapped") !=
            len({r["workKey"] for r in rules})
            or live["summary"].get("mappedSourceWorkPairs") != len(rules)):
        raise ValueError("Incomplete research mapping summary")
    expected = {(r["workKey"], r["url"]): r for r in rules}
    found = {}
    for obs in observations:
        identity = obs["workKey"], obs["url"]
        rule = expected.get(identity)
        if (rule is None or obs.get("expectedLabel") != rule["label"]
                or obs.get("expectedUnit") != rule["unit"]
                or obs.get("scopeStatus") != rule["scope"]
                or obs.get("scopeReason") != rule["scopeReason"]):
            raise ValueError("Research observation does not match pinned exact rule")
        found[identity] = obs
    if set(expected) != set(found):
        raise ValueError("Research observations do not cover exact rules")
    calculated_drift = audit_drift(catalog, live)
    if (not isinstance(drift, dict)
            or drift != calculated_drift
            or drift.get("summary", {}).get("approvedForPublication") != 0):
        raise ValueError("Labor drift report was altered or is inconsistent")

    work_keys = [*LABOR_KEYS]
    if "startPuttyWork" in catalog.get("laborStagePrices", {}):
        work_keys.append("startPuttyWork")
    mapped = {r["workKey"] for r in rules}
    unmapped = set(work_keys) - mapped
    leads_by_key = check_leads(leads_doc, unmapped)
    grouped = defaultdict(list)
    for item in observations:
        grouped[item["workKey"]].append(item)
    drifts = {row["workKey"]: row for row in drift["workReview"]}
    if set(drifts) != set(work_keys):
        raise ValueError("Labor drift does not review all catalog work types")

    work_review = []
    for key in work_keys:
        entries = grouped[key]
        quotes = [x for x in entries if x["status"] == "research_quote"]
        rejected_units = sum(x.get("reason") == "unit_mismatch" for x in entries)
        scope_reviews = sum(x["scopeStatus"] == "review_required" for x in quotes)
        eligible_sites = drifts[key]["boundedAlignedIndependentDomains"]
        unavailable = sum(x["status"] == "not_checked" for x in entries)

        if not entries:
            group, priority, action = "no_exact_mapping", 1, "verify_specific_technology_before_mapping"
        elif rejected_units:
            group, priority, action = "unit_conflict", 2, "confirm_source_unit_without_conversion"
        elif not quotes:
            group, priority, action = "no_live_exact_quote", 3, "check_exact_row_and_source_availability"
        elif scope_reviews:
            group, priority, action = "scope_not_confirmed", 4, "verify_layers_thickness_and_included_operations"
        elif eligible_sites < 2:
            group, priority, action = "insufficient_bounded_sources", 5, "find_independent_scope_matched_dated_quote"
        else:
            group, priority, action = "preliminary_comparison_only", 6, "verify_individual_price_dates_and_tier_policy"

        # A read-only comparison may identify outliers, but never a new tariff.
        if drifts[key]["screeningStatus"] == "outside_preliminary_band_manual_review":
            group, priority, action = "drift_outlier_manual_review", 2, "inspect_exact_scope_before_any_price_decision"
        work_review.append({
            "workKey": key,
            "unit": required_unit(key),
            "priority": priority,
            "reviewGroup": group,
            "nextManualAction": action,
            "configuredExactRows": len(entries),
            "exactResearchQuotes": len(quotes),
            "unavailableOrSkippedRows": unavailable,
            "rejectedUnitRows": rejected_units,
            "scopeReviewQuotes": scope_reviews,
            "comparableBoundedIndependentSites": eligible_sites,
            "manualLeadCount": len(leads_by_key.get(key, [])),
            "manualLeads": [{
                "source": urlparse(lead["url"]).hostname,
                "url": lead["url"], "label": lead["label"],
                "technology": lead["technology"],
                "scopeLimitation": lead["scopeLimitation"],
                "accessNeedsVerification": lead["accessNeedsVerification"],
                "approvedForPublication": False,
            } for lead in leads_by_key.get(key, [])],
            "priceDateVerified": False,
            "approvedForPublication": False,
        })

    work_review.sort(key=lambda row: (row["priority"], row["workKey"]))
    groups = Counter(r["reviewGroup"] for r in work_review)
    return {
        "schemaVersion": 1,
        "status": "manual_research_only",
        "country": "MD", "currency": "MDL",
        "catalogVersion": catalog["catalogVersion"],
        "quoteReportCheckedAtUtc": live["checkedAtUtc"],
        "summary": {
            "catalogLaborRates": len(LABOR_KEYS),
            "optionalStartPuttyIncluded": "startPuttyWork" in work_keys,
            "workTypesReviewed": len(work_review),
            "workTypesWithExactMappings": len(mapped),
            "workTypesWithoutExactMappings": len(unmapped),
            "manualLeadsForUnmappedWork": len(leads_doc["leads"]),
            "reviewGroups": dict(sorted(groups.items())),
            "publicationReadyLaborRates": 0,
        },
        "workReview": work_review,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "automaticLaborPublicationEnabled": False,
        "note": "Research leads are NOT prices. No tier is verified or approved for publication.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--sources", type=Path, default=Path("labor_market_sources.json"))
    parser.add_argument("--rules", type=Path, default=Path("labor_live_match_rules.json"))
    parser.add_argument("--quotes", type=Path, default=Path("live_labor_quotes.json"))
    parser.add_argument("--drift", type=Path, default=Path("labor_drift_review.json"))
    parser.add_argument("--leads", type=Path, default=Path("labor_manual_research_leads.json"))
    parser.add_argument("--report", type=Path, default=Path("labor_manual_review_queue.json"))
    args = parser.parse_args(argv)
    try:
        report = build_queue(*(load(path) for path in (
            args.catalog, args.sources, args.rules, args.quotes, args.drift, args.leads)))
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"LABOR MANUAL QUEUE FAILED: {error}", file=sys.stderr)
        return 1
    summary = report["summary"]
    print("=== COSTARO LABOR MANUAL RESEARCH QUEUE ===")
    print(f"Works reviewed: {summary['workTypesReviewed']}")
    print(f"Exact research mappings: {summary['workTypesWithExactMappings']}")
    print(f"No exact mappings: {summary['workTypesWithoutExactMappings']}")
    print(f"Technology-specific leads, NOT prices: {summary['manualLeadsForUnmappedWork']}")
    print("Approved or changed prices: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
