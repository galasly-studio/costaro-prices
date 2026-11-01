#!/usr/bin/env python3
"""Plan safe material price changes; never modify or publish prices.json.

This is a deliberately fail-closed bridge between monthly price observations
and the COSTARO application catalog. An observation is *not* a tier price:
one reviewed product/pack/tier mapping, two independent shops, exact SKU and
strong extraction, fresh evidence and app compatibility are all mandatory.
"""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import statistics
from urllib.parse import urlparse

from validate_app_catalog import load, validate


TIERS = ("budget", "standard", "premium")
MAX_AGE = timedelta(hours=24)
MAX_FUTURE_CLOCK_DRIFT = timedelta(minutes=5)
MIN_CHANGE = 0.02
MAX_CHANGE = 0.08
MAX_STORE_SPREAD = 0.12


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _store(value):
    return str(value).strip().casefold() if isinstance(value, str) else ""


def _domain(url):
    if not isinstance(url, str):
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not host.endswith(".md"):
        return ""
    if parsed.username or parsed.password or parsed.port:
        return ""
    return host.removeprefix("www.")


def _utc(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _pack_tiers(entry, source):
    """Only exact kg retail packages can match current kg catalog entries.

    Never scale a 20 kg store price to an 8 kg catalog pack, even if the
    arithmetic looks plausible: shelf price and retail packaging differ.
    """
    if source.get("unit") not in ("bag", "bucket"):
        return []
    amount = source.get("packageWeightKg")
    if not _number(amount) or not isinstance(entry, dict):
        return []
    return [tier for tier in TIERS
            if isinstance(entry.get(tier), dict)
            and entry[tier].get("unit") == "кг"
            and entry[tier].get("amount") == amount]


def _evidence(sources, observation):
    configured = sources.get("sources")
    recorded = observation.get("observations") if isinstance(observation, dict) else None
    if not isinstance(configured, list) or len(configured) < 2:
        return None, "less_than_two_configured_shops"
    if not isinstance(recorded, list) or len(configured) != len(recorded):
        return None, "observation_count_mismatch"
    shops, domains, prices = set(), set(), []
    for expected, actual in zip(configured, recorded):
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            return None, "malformed_source_or_observation"
        shop, domain = _store(expected.get("store")), _domain(expected.get("url"))
        sku = str(expected.get("productCode", "")).strip()
        if not shop or not domain or not sku:
            return None, "unverified_store_url_or_sku"
        if shop in shops or domain in domains:
            return None, "shops_not_independent"
        if (actual.get("store") != expected.get("store")
                or actual.get("url") != expected.get("url")
                or str(actual.get("productCode", "")).strip() != sku):
            return None, "observation_does_not_match_source"
        if actual.get("status") != "candidate":
            return None, "store_unavailable_or_ambiguous"
        if actual.get("extractionMethod") != "product_microdata":
            return None, "product_identity_not_strongly_verified"
        price = actual.get("price")
        if not _number(price):
            return None, "invalid_price"
        shops.add(shop)
        domains.add(domain)
        prices.append(float(price))
    if (max(prices) - min(prices)) / min(prices) > MAX_STORE_SPREAD:
        return None, "independent_store_prices_disagree"
    return round(statistics.median(prices), 2), None


def _policy_valid(policy):
    if not isinstance(policy, dict) or policy.get("schemaVersion") != 1:
        raise ValueError("Invalid material publication policy schema")
    if type(policy.get("enabled")) is not bool:
        raise ValueError("Policy enabled must be a JSON boolean")
    approvals = policy.get("approvedMappings")
    if not isinstance(approvals, list):
        raise ValueError("approvedMappings must be an array")
    ids = []
    assigned_tiers = []
    for item in approvals:
        if not isinstance(item, dict):
            raise ValueError("Invalid approved tier mapping")
        if (not isinstance(item.get("observationId"), str)
                or item.get("tier") not in TIERS
                or not isinstance(item.get("catalogMaterialKey"), str)):
            raise ValueError("Every approval needs observationId, tier, catalogMaterialKey")
        ids.append(item["observationId"])
        assigned_tiers.append((item["catalogMaterialKey"], item["tier"]))
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate approved observationId")
    if len(assigned_tiers) != len(set(assigned_tiers)):
        raise ValueError("Duplicate approved catalog material/tier")


def plan(catalog, baseline, sources, observations, policy, now=None):
    """Return a human-readable report and a validated *in-memory* draft."""
    _policy_valid(policy)
    current_errors = validate(catalog, baseline)
    if current_errors:
        raise ValueError("Current catalog is incompatible: " + "; ".join(current_errors))
    if sources.get("country") != "MD" or sources.get("currency") != "MDL":
        raise ValueError("Source country/currency are not MD/MDL")
    if observations.get("country") != "MD" or observations.get("currency") != "MDL":
        raise ValueError("Observation country/currency are not MD/MDL")
    if not isinstance(sources.get("materials"), list) or not isinstance(observations.get("materials"), list):
        raise ValueError("Invalid material source/observation list")
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    observed_at = _utc(observations.get("generatedAt"))
    fresh = (observed_at is not None and
             now - MAX_AGE <= observed_at <= now + MAX_FUTURE_CLOCK_DRIFT)
    source_by_id = {item["id"]: item for item in sources["materials"]}
    seen = {item["id"]: item for item in observations["materials"]}
    if len(source_by_id) != len(sources["materials"]) or len(seen) != len(observations["materials"]):
        raise ValueError("Duplicate material observation/source ID")

    candidate = deepcopy(catalog)
    approvals = {item["observationId"]: item for item in policy["approvedMappings"]}
    if set(approvals) - set(source_by_id):
        raise ValueError("Approval references an unknown observationId")
    rows = []
    for material_id, source in source_by_id.items():
        key = source.get("catalogMaterialKey")
        entry = catalog["materialPrices"].get(key)
        matching = _pack_tiers(entry, source)
        row = {"observationId": material_id, "catalogMaterialKey": key,
               "matchingPackTiers": matching, "status": "held", "reason": None}
        approval = approvals.get(material_id)
        if not fresh:
            row["reason"] = "observations_not_fresh"
        elif entry is None:
            row["reason"] = "unknown_catalog_material"
        elif not matching:
            row["reason"] = "source_pack_does_not_match_catalog_pack"
        elif source.get("priceTier") not in TIERS:
            row["reason"] = "source_has_no_reviewed_price_tier"
        elif not policy["enabled"]:
            row["reason"] = "automatic_proposals_disabled"
        elif approval is None:
            row["reason"] = "tier_mapping_not_approved"
        elif (approval["tier"] != source["priceTier"]
              or approval["catalogMaterialKey"] != key
              or approval["tier"] not in matching):
            row["reason"] = "approved_mapping_does_not_match_source_or_pack"
        else:
            median, error = _evidence(source, seen.get(material_id))
            if error:
                row["reason"] = error
            else:
                tier = approval["tier"]
                previous = catalog["materialPrices"][key][tier]["price"]
                baseline_price = baseline["materialPrices"][key][tier]["price"]
                movement = (median - previous) / previous
                if abs(movement) < MIN_CHANGE:
                    row["reason"] = "price_change_below_two_percent"
                elif abs(movement) > MAX_CHANGE:
                    row["reason"] = "price_change_above_eight_percent"
                elif not baseline_price * 0.7 <= median <= baseline_price * 1.3:
                    row["reason"] = "outside_embedded_app_thirty_percent_limit"
                else:
                    candidate["materialPrices"][key][tier]["price"] = median
                    errors = validate(candidate, baseline)
                    if errors:
                        candidate["materialPrices"][key][tier]["price"] = previous
                        row["reason"] = "complete_catalog_validation_failed"
                    else:
                        row.update({"status": "proposed", "previousMDL": previous,
                                    "proposedMDL": median, "changePercent": round(movement * 100, 2)})
        rows.append(row)
    # A future publishing workflow must separately authorize, version and deploy
    # any proposal. No file returned by this script is an approved publication.
    result = {"schemaVersion": 1, "status": "read_only_proposals",
              "generatedAt": now.isoformat(), "policyEnabled": policy["enabled"],
              "proposedCount": sum(row["status"] == "proposed" for row in rows),
              "verifiedForPublication": False, "publishedPricesChanged": False,
              "materials": rows}
    return result, candidate


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--baseline", type=Path, default=Path("app_embedded_baseline.json"))
    parser.add_argument("--sources", type=Path, default=Path("price_sources.json"))
    parser.add_argument("--observations", type=Path, default=Path("price_observations.json"))
    parser.add_argument("--policy", type=Path, default=Path("material_update_policy.json"))
    parser.add_argument("--report", type=Path, default=Path("material_update_proposals.json"))
    args = parser.parse_args(argv)
    report, _unused = plan(load(args.catalog), load(args.baseline),
                           load(args.sources), load(args.observations), load(args.policy))
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("=== COSTARO SAFE MATERIAL UPDATE PLAN ===")
    print("Proposals:", report["proposedCount"])
    print("Automatic proposals enabled:", report["policyEnabled"])
    for item in report["materials"]:
        if item["status"] == "proposed" or item["matchingPackTiers"]:
            print(item["catalogMaterialKey"], "|", item["status"].upper(),
                  "|", item.get("reason") or f"{item['previousMDL']} -> {item['proposedMDL']} MDL")
    print("Report saved:", args.report)
    print("prices.json was NOT changed or published.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
