#!/usr/bin/env python3
"""Build a human-only budget/standard/premium review queue from monthly evidence.

No tiers are assigned, no price changes are proposed for publication, and no
app catalog, policy or source file is written. Product quality cannot be
inferred from retail prices; tierCandidateForReview is only a review label.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import statistics
from urllib.parse import urlparse

from plan_verified_material_updates import TIERS, _pack_tiers, _utc
from validate_app_catalog import load, validate


def _index(rows, name):
    if not isinstance(rows, list):
        raise ValueError(f"{name} must be a list")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError(f"{name} has an invalid ID")
        if row["id"] in result:
            raise ValueError(f"Duplicate ID in {name}: {row['id']}")
        result[row["id"]] = row
    return result


def _fresh(iso_time, now):
    observed = _utc(iso_time)
    return (observed is not None and
            (now - observed).total_seconds() <= 24 * 3600 and
            (observed - now).total_seconds() <= 5 * 60)


def _valid_price(price):
    return (isinstance(price, (int, float)) and not isinstance(price, bool)
            and math.isfinite(price) and price > 0)


def _evidence(product, observation, audit_row, *, fresh):
    """Recheck source/observation identity; never trust a count alone."""
    configured = product.get("sources")
    recorded = observation.get("observations") if isinstance(observation, dict) else None
    if not fresh:
        return None, [], "stale_or_future_observations"
    if not isinstance(configured, list) or len(configured) < 2:
        return None, [], "fewer_than_two_sources"
    if not isinstance(recorded, list) or len(recorded) != len(configured):
        return None, [], "source_observation_count_mismatch"
    shops, hosts, evidence = set(), set(), []
    for expected, actual in zip(configured, recorded):
        if not isinstance(expected, dict) or not isinstance(actual, dict):
            return None, [], "invalid_source_or_observation"
        store = str(expected.get("store", "")).strip()
        code = str(expected.get("productCode", "")).strip()
        url = expected.get("url")
        if not store or not isinstance(url, str):
            return None, [], "invalid_source_identity"
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower().removeprefix("www.")
        if (parsed.scheme != "https" or not host.endswith(".md") or
                parsed.username or parsed.password or parsed.port or
                store.casefold() in shops or host in hosts):
            return None, [], "sources_not_independent_or_not_md"
        if (actual.get("store") != store or actual.get("url") != url or
                str(actual.get("productCode", "")).strip() != code):
            return None, [], "observation_source_mismatch"
        if actual.get("status") != "candidate" or not _valid_price(actual.get("price")):
            return None, [], "unavailable_or_invalid_price"
        shops.add(store.casefold())
        hosts.add(host)
        evidence.append({"store": store, "url": url, "productCode": code,
                         "priceMDL": float(actual["price"]),
                         "extractionMethod": actual.get("extractionMethod")})
    prices = [row["priceMDL"] for row in evidence]
    if (max(prices) - min(prices)) / min(prices) > 0.20:
        return None, evidence, "store_price_spread_exceeds_twenty_percent"
    if not isinstance(audit_row, dict) or audit_row.get("comparisonReady") is not True:
        return None, evidence, "audit_not_comparison_ready"
    median = round(statistics.median(prices), 2)
    report_median = audit_row.get("candidateMedianMDL")
    if not _valid_price(report_median) or abs(report_median - median) > 0.011:
        return None, evidence, "audit_median_does_not_match_observations"
    return median, evidence, None


def build(catalog, baseline, sources, observations, audit, policy, *, now=None):
    errors = validate(catalog, baseline)
    if errors:
        raise ValueError("Catalog incompatible with embedded app: " + "; ".join(errors))
    for label, doc in (("catalog", catalog), ("sources", sources),
                       ("observations", observations), ("audit", audit)):
        if doc.get("country") != "MD" or doc.get("currency") != "MDL":
            raise ValueError(f"{label} must use Moldova/MDL")
    if policy.get("enabled") is not False or policy.get("approvedMappings") != []:
        raise ValueError("Manual report requires disabled policy and no approved mappings")
    if sources.get("automaticPublicationEnabled") is not False:
        raise ValueError("Source publication must remain disabled")
    if audit.get("status") != "audit_only":
        raise ValueError("Audit must be read-only")

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    fresh = _fresh(observations.get("generatedAt"), now)
    source_by_id = _index(sources.get("materials"), "source products")
    observation_by_id = _index(observations.get("materials"), "observations")
    audit_by_id = _index(audit.get("materials"), "audit rows")
    if set(source_by_id) != set(observation_by_id) or set(source_by_id) != set(audit_by_id):
        raise ValueError("Sources, observations and audit IDs differ")

    products = []
    by_material = {key: [] for key in catalog["materialPrices"]}
    for product_id, product in source_by_id.items():
        material_key = product.get("catalogMaterialKey")
        if material_key not in by_material:
            raise ValueError(f"Unknown catalog material key: {material_key}")
        hint = product.get("tierCandidateForReview")
        if hint is not None and hint not in TIERS:
            raise ValueError(f"Unknown tier hint for {product_id}")
        if product.get("priceTier") is not None:
            raise ValueError(f"Unexpected approved tier in source: {product_id}")
        matching_pack_tiers = _pack_tiers(catalog["materialPrices"][material_key], product)
        median, shop_prices, evidence_error = _evidence(
            product, observation_by_id[product_id], audit_by_id[product_id], fresh=fresh,
        )
        if hint is None:
            reason = "tier_not_assessed_by_human"
        elif hint not in matching_pack_tiers:
            reason = "retail_pack_does_not_match_catalog_tier"
        elif evidence_error:
            reason = evidence_error
        else:
            reason = None
        row = {
            "id": product_id, "catalogMaterialKey": material_key,
            "tierHintForHumanReview": hint, "exactPackMatchingTiers": matching_pack_tiers,
            "candidateMedianMDL": median,
            "sourceObservations": shop_prices,
            "status": "manual_review_candidate" if reason is None else "held",
            "reason": reason,
            "skuAndMethodReviewRequired": bool(shop_prices) and any(
                not row["productCode"] or row["extractionMethod"] != "product_microdata"
                for row in shop_prices
            ),
            "tierQualityReviewed": False,
            "approvedForPublication": False,
        }
        products.append(row)
        by_material[material_key].append(row)

    material_rows = []
    for key, tier_data in catalog["materialPrices"].items():
        tiers = {}
        for tier in TIERS:
            current = tier_data.get(tier) if isinstance(tier_data, dict) else None
            if isinstance(current, dict):
                amount = current.get("price")
            else:
                amount = current
            options = [row["id"] for row in by_material[key]
                       if row["status"] == "manual_review_candidate"
                       and row["tierHintForHumanReview"] == tier]
            tiers[tier] = {"currentCatalogMDL": amount, "reviewCandidateIDs": options}
        material_rows.append({"catalogMaterialKey": key, "tiers": tiers,
                              "hasCompleteReviewCandidateSet": all(
                                  len(tiers[tier]["reviewCandidateIDs"]) == 1
                                  for tier in TIERS),
                              "approvedForPublication": False})

    ready = [row for row in products if row["status"] == "manual_review_candidate"]
    result = {
        "schemaVersion": 1, "country": "MD", "currency": "MDL",
        "status": "human_review_only", "generatedAt": now.isoformat(),
        "observationsFresh": fresh, "automaticPublicationEnabled": False,
        "pricesChanged": False, "approvedTierMappings": 0,
        "summary": {
            "catalogMaterialCount": len(material_rows), "productGroupCount": len(products),
            "reviewCandidates": len(ready),
            "materialsWithCompleteThreeTierCandidateSet": sum(
                row["hasCompleteReviewCandidateSet"] for row in material_rows),
            "heldProductGroups": len(products) - len(ready),
        },
        "products": products, "catalogMaterials": material_rows,
    }
    return result


def summary_markdown(report):
    """Human-readable companion for the uploaded Actions artifact."""
    lines = ["# COSTARO — кандидаты на ручную проверку трёх уровней цен", "",
             "**Только исследование; цены приложения не менялись.**", "",
             "Цена не доказывает качество. Подсказка уровня не является утверждением.", "",
             f"Найдено кандидатных товаров: **{report['summary']['reviewCandidates']}**",
             f"Полных троек для ручного анализа: **{report['summary']['materialsWithCompleteThreeTierCandidateSet']}**", "",
             "| Материал | Уровень (подсказка) | Артикул исследования | Медиана, MDL | Проверка идентичности |",
             "|---|---|---|---:|---|"]
    for row in report["products"]:
        if row["status"] != "manual_review_candidate":
            continue
        label = "обязательно" if row["skuAndMethodReviewRequired"] else "обязательно (качество)"
        lines.append(f"| `{row['catalogMaterialKey']}` | {row['tierHintForHumanReview']} | "
                     f"`{row['id']}` | {row['candidateMedianMDL']:.2f} | {label} |")
    lines.extend(["", "## Почему остальные товары не распределены", "",
                  "Большинство товарных групп пока не имеют подтверждённого человеком "
                  "соответствия бюджетному, стандартному или премиальному классу. "
                  "Нельзя автоматически относить товар к классу только по его цене.", "",
                  "Для окончательного утверждения потребуется проверить SKU, фасовку, "
                  "единицу, качество и свойства материала. Сопоставление разных "
                  "магазинов само по себе не разрешает публикацию.", "",
                  "`material_update_policy.json` остаётся выключенным. "
                  "`prices.json` не изменён."])
    return "\n".join(lines) + "\n"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--baseline", type=Path, default=Path("app_embedded_baseline.json"))
    parser.add_argument("--sources", type=Path, default=Path("price_sources.json"))
    parser.add_argument("--observations", type=Path, default=Path("price_observations.json"))
    parser.add_argument("--audit", type=Path, default=Path("price_audit_report.json"))
    parser.add_argument("--policy", type=Path, default=Path("material_update_policy.json"))
    parser.add_argument("--report", type=Path, default=Path("material_tier_review.json"))
    parser.add_argument("--summary", type=Path, default=Path("material_tier_review_RU.md"))
    args = parser.parse_args(argv)
    report = build(load(args.catalog), load(args.baseline), load(args.sources),
                   load(args.observations), load(args.audit), load(args.policy))
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.summary.write_text(summary_markdown(report), encoding="utf-8")
    print("=== COSTARO MATERIAL TIER MANUAL REVIEW ===")
    print("Candidate product groups:", report["summary"]["reviewCandidates"])
    print("Complete three-tier sets for human review:", report["summary"]["materialsWithCompleteThreeTierCandidateSet"])
    print("Held product groups:", report["summary"]["heldProductGroups"])
    print("Published prices were NOT changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
