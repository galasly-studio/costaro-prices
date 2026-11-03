#!/usr/bin/env python3
"""Fail-closed, read-only drift screening of provisional labor table quotes.

This does NOT verify any individual tariff/date, recommend tier reassignment,
change prices, or authorize publication. It identifies review priorities only.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from audit_labor_prices import LABOR_KEYS, catalog_errors, load, positive, required_unit
from check_labor_source_health import validate_url


ALL_KEYS = set(LABOR_KEYS) | {"startPuttyWork"}
SOURCE_STATUSES = {"research_quote", "rejected", "not_found", "not_checked"}
KINDS = {"fixed_price", "range_with_average", "range_without_average", "lower_bound"}
MARGIN = 0.20  # Only a screening tolerance, NEVER a price-update threshold.


def _check_report(catalog: dict, live: dict) -> list[dict]:
    errors = catalog_errors(catalog)
    if errors:
        raise ValueError("Catalog failed safety validation: " + "; ".join(errors))
    if (live.get("status") != "technical_research_only"
            or live.get("country") != "MD" or live.get("currency") != "MDL"
            or live.get("catalogVersion") != catalog["catalogVersion"]
            or live.get("publishedPricesChanged") is not False
            or live.get("flutterCalculationsChanged") is not False
            or live.get("automaticLaborPublicationEnabled") is not False):
        raise ValueError("Unsafe or mismatched research report")
    observations = live.get("observations")
    if not isinstance(observations, list) or not observations:
        raise ValueError("Missing labor observations")
    if (not isinstance(live.get("summary"), dict)
            or live["summary"].get("mappedSourceWorkPairs") != len(observations)
            or live["summary"].get("publicationReadyLaborRates") != 0):
        raise ValueError("Observation totals or publication safety are inconsistent")
    seen = set()
    for obs in observations:
        if not isinstance(obs, dict):
            raise ValueError("Invalid labor observation")
        key = obs.get("workKey")
        if key not in ALL_KEYS or key not in catalog["laborPrices"] | catalog.get("laborStagePrices", {}):
            raise ValueError("Unknown labor rate in research observation")
        try:
            domain = validate_url(obs["url"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("Invalid research URL") from error
        if (obs.get("source") != domain
                or obs.get("expectedUnit") != required_unit(key)
                or obs.get("status") not in SOURCE_STATUSES
                or obs.get("scopeStatus") not in {"preliminarily_aligned", "review_required"}
                or obs.get("priceDateVerified") is not False
                or obs.get("approvedForPublication") is not False):
            raise ValueError("Invalid or publication-enabled labor observation")
        identity = (key, obs["url"])
        if identity in seen:
            raise ValueError("Duplicate work/page research observation")
        seen.add(identity)
        if obs["status"] == "research_quote":
            if (obs.get("priceKind") not in KINDS
                    or obs.get("unit") != required_unit(key)
                    or not positive(obs.get("minimumMDL"))):
                raise ValueError("Malformed quote amount or unit")
            maximum = obs.get("maximumMDL")
            if obs["priceKind"] == "lower_bound":
                if maximum is not None:
                    raise ValueError("Lower-bound quote cannot have a maximum")
            elif not positive(maximum) or maximum < obs["minimumMDL"]:
                raise ValueError("Malformed bounded quote")
            elif obs["priceKind"] == "fixed_price" and maximum != obs["minimumMDL"]:
                raise ValueError("Fixed quote has different min/max values")
            elif obs["priceKind"] == "range_without_average" and "averageMDL" in obs:
                raise ValueError("Two-point range must not invent an average")
        elif "minimumMDL" in obs or "maximumMDL" in obs:
            raise ValueError("Unmatched row has price fields")
    return observations


def audit(catalog: dict, live: dict) -> dict:
    """Compare standard tier to provisional union only with two domains."""
    observations = _check_report(catalog, live)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for obs in observations:
        grouped[obs["workKey"]].append(obs)

    reviews = []
    for key in [*LABOR_KEYS, *(["startPuttyWork"] if "startPuttyWork" in
                                     catalog.get("laborStagePrices", {}) else [])]:
        entries = grouped[key]
        quotes = [o for o in entries if o["status"] == "research_quote"]
        eligible = [o for o in quotes
                    if o["scopeStatus"] == "preliminarily_aligned"
                    and o["priceKind"] != "lower_bound"]
        domains = sorted({o["source"] for o in eligible})
        tiers = (catalog["laborStagePrices"][key] if key == "startPuttyWork"
                 else catalog["laborPrices"][key])
        market_band = None
        if len(domains) >= 2:
            low = min(o["minimumMDL"] for o in eligible)
            high = max(o["maximumMDL"] for o in eligible)
            expanded_low = round(low * (1 - MARGIN), 2)
            expanded_high = round(high * (1 + MARGIN), 2)
            outside = not (expanded_low <= tiers["standard"] <= expanded_high)
            market_band = {"provisionalMinimumMDL": low,
                           "provisionalMaximumMDL": high,
                           "screeningMinimumMDL": expanded_low,
                           "screeningMaximumMDL": expanded_high}
            status = ("outside_preliminary_band_manual_review" if outside
                      else "inside_preliminary_band_not_verified")
        elif domains:
            status = "insufficient_independent_sources"
        else:
            status = "not_comparable"
        reviews.append({
            "workKey": key,
            "catalogStandardMDL": tiers["standard"],
            "unit": required_unit(key),
            "mappedPages": len(entries),
            "quoteRows": len(quotes),
            "quotesNeedingScopeReview": sum(
                o["scopeStatus"] == "review_required" for o in quotes),
            "lowerBoundsExcluded": sum(o["priceKind"] == "lower_bound" for o in quotes),
            "rejectedUnitRows": sum(o["status"] == "rejected" and
                                    o.get("reason") == "unit_mismatch" for o in entries),
            "boundedAlignedIndependentDomains": len(domains),
            "boundedAlignedDomains": domains,
            "marketBandResearchOnly": market_band,
            "screeningStatus": status,
            "priceDateVerified": False,
            "approvedForPublication": False,
        })

    counts = Counter(row["screeningStatus"] for row in reviews)
    return {
        "schemaVersion": 1,
        "status": "technical_research_only",
        "catalogVersion": catalog["catalogVersion"],
        "country": "MD", "currency": "MDL",
        "screeningMarginPercent": 20,
        "summary": {
            "catalogLaborRates": len(LABOR_KEYS),
            "optionalStartPuttyStageIncluded": "startPuttyWork" in
                catalog.get("laborStagePrices", {}),
            "laborRatesReviewed": len(reviews),
            "outsidePreliminaryBandManualReview": counts["outside_preliminary_band_manual_review"],
            "insidePreliminaryBandNotVerified": counts["inside_preliminary_band_not_verified"],
            "insufficientIndependentSources": counts["insufficient_independent_sources"],
            "notComparable": counts["not_comparable"],
            "observedScopeReviewQuotes": sum(row["quotesNeedingScopeReview"] for row in reviews),
            "rejectedUnitRows": sum(row["rejectedUnitRows"] for row in reviews),
            "approvedForPublication": 0,
        },
        "workReview": reviews,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "automaticLaborPublicationEnabled": False,
        "note": ("Two independently hosted preliminary rows only permit a screening "
                 "comparison with the existing standard tier. Individual price "
                 "dates and complete scope are unverified; no new prices are "
                 "suggested and no tier is approved."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--quotes", type=Path, default=Path("live_labor_quotes.json"))
    parser.add_argument("--report", type=Path, default=Path("labor_drift_review.json"))
    args = parser.parse_args(argv)
    try:
        report = audit(load(args.catalog), load(args.quotes))
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        print(f"LABOR DRIFT RESEARCH FAILED: {error}", file=sys.stderr)
        return 1
    sh = report["summary"]
    print("=== COSTARO LABOR DRIFT RESEARCH (NOT VERIFIED) ===")
    print(f"Catalog work rates: {sh['catalogLaborRates']}")
    print(f"Additional start putty stage: {sh['optionalStartPuttyStageIncluded']}")
    print(f"Outside provisional band, manual review: {sh['outsidePreliminaryBandManualReview']}")
    print(f"Not comparable: {sh['notComparable']}")
    print("No prices changed, no tier mapping published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
