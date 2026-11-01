#!/usr/bin/env python3
"""Audit all COSTARO catalog tier units against monitored retail packs.

Fail closed: a store's price for 1000 screws, 15 kg of primer, or a 90 m
roll is not automatically a 100-screw, 3 kg, or 45 m catalog price.
This script audits metadata; it never changes prices or approves mappings.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlparse

from validate_app_catalog import load, validate


TIERS = ("budget", "standard", "premium")
PACK_UNITS = {
    "кг": ({"bag", "bucket", "pack"}, "packageWeightKg"),
    "м²/лист": ({"sheet"}, "packageAreaM2"),
    "м/шт": ({"piece"}, "packageLengthM"),
    "шт/уп": ({"pack"}, "packageQuantity"),
    "м/рул": ({"roll"}, "packageLengthM"),
    "м²/рулон": ({"roll"}, "packageAreaM2"),
}


def _positive_number(v):
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v) and v > 0)


def _scalar_catalog_unit(key):
    if key.endswith("PerPiece"):
        return "piece"
    if key.endswith("PerM2"):
        return "m2"
    if key.endswith("PerM"):
        return "m"
    if key.endswith("PerPoint"):
        return "point"
    return None


def _check_tier(key, tier_data, source):
    """Return physical compatibility, never a product quality classification."""
    src_unit = source.get("unit")
    if isinstance(tier_data, dict):
        unit = tier_data.get("unit")
        amount = tier_data.get("amount")
        if not _positive_number(amount):
            return "unverified", "catalog_amount_invalid", unit, amount, None
        if unit == "уп.":
            if src_unit != "pack":
                return "different_unit", "catalog_one_pack_vs_different_store_unit", unit, amount, None
            return "unverified", "pack_contents_not_defined_in_catalog", unit, amount, None
        expected = PACK_UNITS.get(unit)
        if expected is None:
            return "unverified", "unsupported_catalog_pack_unit", unit, amount, None
        allowed_units, size_field = expected
        if src_unit not in allowed_units:
            return "different_unit", "retail_unit_differs_from_catalog", unit, amount, None
        size = source.get(size_field)
        if not _positive_number(size):
            return "missing_size", "retail_pack_size_not_documented", unit, amount, None
        if not math.isclose(size, amount, rel_tol=0, abs_tol=0.00001):
            return "different_pack", "retail_pack_size_differs_from_catalog", unit, amount, size
        return "exact", "same_unit_and_pack_size", unit, amount, size

    if not _positive_number(tier_data):
        return "unverified", "catalog_price_invalid", None, None, None
    unit = _scalar_catalog_unit(key)
    if unit is None:
        return "unverified", "catalog_scalar_unit_unknown", None, None, None
    if unit == "point":
        return "conversion_review", "pieces_per_point_not_confirmed", unit, 1, source.get("packageQuantity")
    if src_unit == unit:
        return "exact", "same_per_unit_measure", unit, 1, 1
    if src_unit in ("pack", "roll") and unit in ("piece", "m2", "m"):
        qty = source.get({"piece": "packageQuantity", "m2": "packageAreaM2",
                          "m": "packageLengthM"}[unit])
        return "conversion_review", "retail_pack_requires_normalized_price", unit, 1, qty
    return "different_unit", "retail_unit_differs_from_catalog", unit, 1, None


def audit(catalog, baseline, sources, market_audit=None):
    errors = validate(catalog, baseline)
    if errors:
        raise ValueError("Catalog incompatible with app baseline: " + "; ".join(errors))
    if (sources.get("country") != "MD" or sources.get("currency") != "MDL"
            or sources.get("automaticPublicationEnabled") is not False):
        raise ValueError("Unsafe source country, currency or publication policy")
    source_rows = sources.get("materials")
    if not isinstance(source_rows, list):
        raise ValueError("Sources must have a materials list")

    market_rows = None
    if market_audit is not None:
        if (market_audit.get("country") != "MD"
                or market_audit.get("currency") != "MDL"
                or market_audit.get("status") != "audit_only"
                or market_audit.get("automaticPublicationEnabled") is not False
                or market_audit.get("publishedPricesChanged") is not False):
            raise ValueError("Unsafe market report for pack comparison")
        entries = market_audit.get("materials")
        if not isinstance(entries, list) or any(
                not isinstance(r, dict) or not isinstance(r.get("id"), str)
                or not isinstance(r.get("comparisonReady"), bool)
                for r in entries):
            raise ValueError("Invalid market comparison rows")
        market_rows = {r["id"]: r for r in entries}
        if len(market_rows) != len(entries):
            raise ValueError("Duplicate market comparison product ID")

    catalog_prices = catalog["materialPrices"]
    by_material = {key: [] for key in catalog_prices}
    product_rows = []
    product_ids = set()
    for product in source_rows:
        if not isinstance(product, dict) or not isinstance(product.get("id"), str):
            raise ValueError("Source product is invalid")
        product_id, key = product["id"], product.get("catalogMaterialKey")
        if product_id in product_ids:
            raise ValueError("Duplicate product ID")
        product_ids.add(product_id)
        if key not in by_material:
            raise ValueError("Unknown catalog material: " + str(key))
        if product.get("priceTier") is not None:
            raise ValueError("Retail price tier was assigned without manual approval")
        configured = product.get("sources")
        if not isinstance(configured, list):
            raise ValueError("Invalid retail source list")
        hostnames = []
        for retailer in configured:
            if not isinstance(retailer, dict):
                raise ValueError("Invalid retailer")
            url = retailer.get("url")
            parsed = urlparse(url) if isinstance(url, str) else None
            host = (parsed.hostname or "").lower().removeprefix("www.") if parsed else ""
            if not parsed or parsed.scheme != "https" or not host.endswith(".md"):
                raise ValueError("Retailer source URL must be Moldova HTTPS")
            hostnames.append(host)
        if len(hostnames) != len(set(hostnames)):
            raise ValueError("Duplicate retail domain counted as independent")

        checks = {}
        for tier in TIERS:
            state, reason, unit, catalog_amount, retail_amount = _check_tier(
                key, catalog_prices[key][tier], product,
            )
            if not configured:
                state, reason = "unverified", "no_retail_sources"
            checks[tier] = {
                "status": state, "reason": reason,
                "catalogUnit": unit, "catalogPackageAmount": catalog_amount,
                "retailPackageAmount": retail_amount,
            }
        row = {
            "id": product_id, "catalogMaterialKey": key,
            "sourceUnit": product.get("unit"),
            "configuredStores": len(configured),
            "twoShopMetadataPresent": len(configured) >= 2,
            "retailSkuMissing": any(
                not str(store.get("productCode", "")).strip() for store in configured),
            "marketComparisonReady": None if market_rows is None
                else (market_rows[product_id]["comparisonReady"]
                      if product_id in market_rows else False),
            "marketProblems": None if market_rows is None else (
                market_rows[product_id].get("problems", [])
                if product_id in market_rows else ["missing_market_product"]),
            "tierChecks": checks,
            "reviewedTier": False,
            "approvedForPublication": False,
        }
        product_rows.append(row)
        by_material[key].append(row)

    if market_rows is not None:
        if set(market_rows) != product_ids:
            raise ValueError("Market audit does not match configured product IDs")
        for product in product_rows:
            observed = market_rows[product["id"]]
            if observed.get("catalogMaterialKey") != product["catalogMaterialKey"]:
                raise ValueError("Market audit material key mismatch")

    catalog_rows = []
    for key, products in by_material.items():
        tiers = {}
        for tier in TIERS:
            matched = [p["id"] for p in products if p["tierChecks"][tier]["status"] == "exact"]
            with_stores = [p["id"] for p in products
                           if p["tierChecks"][tier]["status"] == "exact"
                           and p["twoShopMetadataPresent"]]
            tiers[tier] = {"unitCompatibleProducts": matched,
                           "unitCompatibleWithTwoStores": with_stores,
                           "marketComparableExactProducts": None if market_rows is None
                           else [p["id"] for p in products
                                 if p["tierChecks"][tier]["status"] == "exact"
                                 and p["twoShopMetadataPresent"]
                                 and p["marketComparisonReady"]],
                           "qualityTierReviewed": False}
        catalog_rows.append({"catalogMaterialKey": key, "tiers": tiers})

    covered_slots = sum(
        bool(row["tiers"][tier]["unitCompatibleWithTwoStores"])
        for row in catalog_rows for tier in TIERS
    )
    fully_covered_materials = sum(
        all(row["tiers"][tier]["unitCompatibleWithTwoStores"] for tier in TIERS)
        for row in catalog_rows
    )
    market_covered_slots = None if market_rows is None else sum(
        bool(row["tiers"][tier]["marketComparableExactProducts"])
        for row in catalog_rows for tier in TIERS
    )

    total = {state: 0 for state in ("exact", "different_unit", "different_pack",
                                    "missing_size", "conversion_review", "unverified")}
    for product in product_rows:
        for checked in product["tierChecks"].values():
            total[checked["status"]] += 1
    result = {
        "schemaVersion": 1, "status": "pack_metadata_audit_only",
        "country": "MD", "currency": "MDL",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "pricesChanged": False, "automaticPublicationEnabled": False,
        "summary": {
            "catalogMaterials": len(catalog_rows),
            "productGroups": len(product_rows),
            "catalogTierSlots": len(catalog_rows) * len(TIERS),
            "catalogTierSlotsWithExactTwoShopMetadata": covered_slots,
            "catalogTierSlotsWithLiveComparableExactPacks": market_covered_slots,
            "catalogMaterialsWithExactPacksForAllTiers": fully_covered_materials,
            "productTierChecks": len(product_rows) * len(TIERS),
            "checksByStatus": total,
            "productsWithTwoConfiguredShops": sum(
                p["twoShopMetadataPresent"] for p in product_rows),
            "productsMissingSku": sum(p["retailSkuMissing"] for p in product_rows),
        },
        "products": product_rows, "materials": catalog_rows,
    }
    return result


def print_summary(report):
    counts = report["summary"]
    print("=== COSTARO PACK / UNIT SAFETY AUDIT ===")
    print("Catalog materials:", counts["catalogMaterials"])
    print("Retail product groups:", counts["productGroups"])
    print("Catalog tier slots:", counts["catalogTierSlots"])
    print("Tier slots with exact packs listed at two shops:",
          counts["catalogTierSlotsWithExactTwoShopMetadata"], "/", counts["catalogTierSlots"])
    if counts["catalogTierSlotsWithLiveComparableExactPacks"] is not None:
        print("Tier slots with exact packs AND two comparable live shop prices:",
              counts["catalogTierSlotsWithLiveComparableExactPacks"],
              "/", counts["catalogTierSlots"])
    print("Materials with exact pack candidates for all tiers:",
          counts["catalogMaterialsWithExactPacksForAllTiers"], "/", counts["catalogMaterials"])
    print("Product-tier pack checks:", counts["productTierChecks"])
    print("Physical alignment:", ", ".join(
        f"{state}={count}" for state, count in counts["checksByStatus"].items()))
    print("=== GROUPS REQUIRING PACK OR UNIT REVIEW ===")
    for item in report["products"]:
        blocking = [f"{tier}:{c['status']}" for tier, c in item["tierChecks"].items()
                    if c["status"] != "exact"]
        if blocking:
            print(item["catalogMaterialKey"], "[" + item["id"] + "]",
                  "|", ", ".join(blocking))
        if item["configuredStores"] < 2:
            print(item["catalogMaterialKey"], "| REVIEW | insufficient_shops")
        if item["retailSkuMissing"]:
            print(item["catalogMaterialKey"], "| REVIEW | retailer_sku_missing")
    if counts["catalogTierSlotsWithLiveComparableExactPacks"] is not None:
        print("=== EXACT PACKS WAITING FOR COMPARABLE LIVE PRICES ===")
        for item in report["products"]:
            if (item["twoShopMetadataPresent"] and not item["marketComparisonReady"]
                    and any(c["status"] == "exact" for c in item["tierChecks"].values())):
                print(item["catalogMaterialKey"], "[" + item["id"] + "]",
                      "| REVIEW |", ",".join(item["marketProblems"] or ["not_comparison_ready"]))
    print("Physical pack compatibility is NOT an approved budget/standard/premium tier.")
    print("Two configured shops are metadata, NOT proof of two successful price observations.")
    print("Published prices were NOT changed.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--baseline", type=Path, default=Path("app_embedded_baseline.json"))
    parser.add_argument("--sources", type=Path, default=Path("price_sources.json"))
    parser.add_argument("--market-audit", type=Path, default=None,
                        help="Optional read-only price_audit_report.json for live comparison counts")
    parser.add_argument("--report", type=Path, default=Path("material_pack_alignment_report.json"))
    args = parser.parse_args(argv)
    report = audit(load(args.catalog), load(args.baseline), load(args.sources),
                   load(args.market_audit) if args.market_audit else None)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print_summary(report)
    print("Report saved:", args.report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
