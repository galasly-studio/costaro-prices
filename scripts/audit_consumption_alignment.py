#!/usr/bin/env python3
"""Audit manufacturer consumption against the frozen COSTARO norm snapshot.

Research only: never modify Flutter calculations, prices, SKU mappings or policy.
The nominal norms come from lib/data/material_norms.dart (2026-11-02 review).
Re-check that Flutter file before any future release using product-specific tiers.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
from urllib.parse import urlparse

from validate_app_catalog import load, validate


# Independently pinned to the reviewed Flutter source. A JSON edit must NOT
# silently change the assumed app calculations without a code review.
APP_NORM_SNAPSHOT = {
    "finishPutty": ("MaterialNorms.finishPuttyKgPerM2", 0.6, 1,
                    "wall_finishing_only"),
    "interiorPaint": ("MaterialNorms.paintKgPerM2TwoCoats", 0.3, 2,
                      "walls_and_ceilings"),
}
EXPECTED_REVIEW_IDS = {
    "glet_mesterul_manole_8kg", "glet_b62_satroc_8kg", "glet_satroc_8kg",
    "romanita_7kg", "euroton_lav_7kg", "sansiro_7kg",
}
TIERS = ("budget", "standard", "premium")
# Maker room-use snapshot verified on 2026-11-02. The Flutter estimate uses
# one generic interiorPaint tier slot for dry and humid room types alike.
# A dry-only paint must therefore never be proposed as a universal tier SKU.
EXPECTED_PAINT_ROOM_USE = {
    "romanita_7kg": "dry_only",
    "euroton_lav_7kg": "dry_and_humid",
    "sansiro_7kg": "dry_and_humid",
}


def _positive(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _manufacturer_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return (parsed.scheme == "https" and parsed.hostname == "supraten.md"
                and bool(parsed.path.strip("/")) and not parsed.username
                and not parsed.password and not parsed.port and not parsed.query)
    except ValueError:
        return False


def _valid_shop_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlparse(value)
        return (parsed.scheme == "https" and parsed.hostname == "gebhardt.md"
                and bool(parsed.path.strip("/")) and not parsed.username
                and not parsed.password and not parsed.port and not parsed.query)
    except ValueError:
        return False


def _range(row):
    values = row.get("manufacturerConsumptionKgPerM2PerCoat")
    if not isinstance(values, dict) or set(values) != {"minimum", "maximum"}:
        raise ValueError("Manufacturer consumption needs exact min/max")
    minimum, maximum = values["minimum"], values["maximum"]
    if not _positive(minimum) or not _positive(maximum) or minimum > maximum:
        raise ValueError("Invalid manufacturer consumption range")
    return float(minimum), float(maximum)


def _packs(kg, package_kg):
    return max(1, math.ceil(kg / package_kg - 1e-10))


def audit(catalog, baseline, sources, evidence, *, area_m2=50.0):
    """Return one read-only report. No network requests or file mutations."""
    errors = validate(catalog, baseline)
    if errors:
        raise ValueError("Catalog incompatible with Flutter baseline: " + "; ".join(errors))
    if not _positive(area_m2):
        raise ValueError("Example area must be finite and positive")
    if (sources.get("country") != "MD" or sources.get("currency") != "MDL"
            or sources.get("automaticPublicationEnabled") is not False):
        raise ValueError("Source country/currency/publication policy mismatch")
    if (not isinstance(evidence, dict) or evidence.get("schemaVersion") != 1
            or evidence.get("country") != "MD" or evidence.get("currency") != "MDL"
            or evidence.get("status") != "technical_research_only"):
        raise ValueError("Invalid technical evidence document")
    if not isinstance(evidence.get("reviewDate"), str) or not evidence["reviewDate"]:
        raise ValueError("Manufacturer review date required")
    if evidence.get("genericInteriorPaintCoversWetRooms") is not True:
        raise ValueError("Generic Flutter paint slot must cover wet rooms")

    app_norms = evidence.get("appNormSnapshot")
    if not isinstance(app_norms, list) or len(app_norms) != len(APP_NORM_SNAPSHOT):
        raise ValueError("Incomplete Flutter norm snapshot")
    norm_by_key = {}
    for item in app_norms:
        if not isinstance(item, dict):
            raise ValueError("Malformed Flutter norm snapshot")
        key = item.get("catalogMaterialKey")
        if key not in APP_NORM_SNAPSHOT or key in norm_by_key:
            raise ValueError("Unknown or duplicate Flutter norm snapshot")
        label, value, coats, scope = APP_NORM_SNAPSHOT[key]
        if (item.get("codeConstant") != label
                or item.get("kgPerM2ForConfiguredCoats") != value
                or type(item.get("coats")) is not int or item["coats"] != coats
                or item.get("scope") != scope):
            raise ValueError("Flutter norm snapshot differs from reviewed code")
        norm_by_key[key] = (value, coats, scope)

    configured = sources.get("materials")
    rows = evidence.get("products")
    if not isinstance(configured, list) or not isinstance(rows, list):
        raise ValueError("Missing product records")
    product_by_id = {row.get("id"): row for row in configured if isinstance(row, dict)}
    if len(product_by_id) != len(configured):
        raise ValueError("Duplicate source product IDs")
    if len(rows) != len(EXPECTED_REVIEW_IDS):
        raise ValueError("Expected six manufacturer-reviewed products")
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError("Malformed technical product")
    if {row.get("id") for row in rows} != EXPECTED_REVIEW_IDS:
        raise ValueError("Technical product IDs differ from review set")

    results = []
    for row in rows:
        product_id = row["id"]
        source = product_by_id.get(product_id)
        key = row.get("catalogMaterialKey")
        hint = row.get("tierHintForHumanReview")
        package_kg = row.get("packageWeightKg")
        if (not isinstance(source, dict) or key not in norm_by_key
                or source.get("catalogMaterialKey") != key
                or hint not in TIERS or source.get("tierCandidateForReview") != hint
                or source.get("priceTier") is not None or source.get("unit") != "bucket"
                or not _positive(package_kg)
                or source.get("packageWeightKg") != package_kg
                or not _manufacturer_url(row.get("manufacturerUrl"))):
            raise ValueError(f"Unverified technical identity or package: {product_id}")
        if key == "interiorPaint":
            if row.get("manufacturerRoomUse") != EXPECTED_PAINT_ROOM_USE.get(product_id):
                raise ValueError(f"Manufacturer room-use evidence mismatch: {product_id}")
            room_use = row["manufacturerRoomUse"]
            room_coverage = ("blocked_dry_only_for_generic_all_room_tier"
                             if room_use == "dry_only" else "covers_dry_and_humid_rooms")
        else:
            if "manufacturerRoomUse" in row:
                raise ValueError(f"Unexpected room-use assessment for putty: {product_id}")
            room_use, room_coverage = "not_assessed", "not_assessed_for_putty"
        for tier in TIERS:
            slot = catalog["materialPrices"][key][tier]
            if not isinstance(slot, dict) or slot.get("amount") != package_kg:
                raise ValueError(f"App catalog pack changed for {product_id}")
        minimum, maximum = _range(row)
        app_total, coats, scope = norm_by_key[key]
        low, high = minimum * coats, maximum * coats
        if app_total < low - 1e-9:
            state = "app_norm_below_manufacturer_minimum"
        elif app_total > high + 1e-9:
            state = "app_norm_above_manufacturer_maximum"
        elif high > app_total * 1.20 + 1e-9:
            state = "wide_consumption_range_requires_review"
        else:
            state = "preliminary_norm_within_manufacturer_range"
        result = {
            "id": product_id,
            "catalogMaterialKey": key,
            "tierHintForHumanReview": hint,
            "scope": scope,
            "manufacturerUrl": row["manufacturerUrl"],
            "packageWeightKg": package_kg,
            "manufacturerKgPerM2ForConfiguredCoats": {
                "minimum": round(low, 4), "maximum": round(high, 4)},
            "appPreliminaryKgPerM2": app_total,
            "exampleAreaM2": area_m2,
            "examplePackages": {
                "appPreliminary": _packs(area_m2 * app_total, package_kg),
                "manufacturerMinimum": _packs(area_m2 * low, package_kg),
                "manufacturerMaximum": _packs(area_m2 * high, package_kg),
            },
            "status": state,
            "requiresConsumptionReview": state != "preliminary_norm_within_manufacturer_range",
            "manufacturerRoomUse": room_use,
            "roomCoverageStatus": room_coverage,
            "roomCoverageCompatibleWithGenericTier": (
                room_use == "dry_and_humid" if key == "interiorPaint" else False),
            "requiresRoomUseReview": room_use == "dry_only",
            "tierQualityApproved": False,
            "approvedForPublication": False,
        }
        results.append(result)

    alternatives = evidence.get("alternativesForHumanResearch")
    if not isinstance(alternatives, list) or len(alternatives) != 1:
        raise ValueError("Expected one proposed alternative for research")
    option = alternatives[0]
    if (not isinstance(option, dict)
            or option.get("replacesCandidateId") != "sansiro_7kg"
            or option.get("name") != "Euroton Eco 7kg"
            or option.get("catalogMaterialKey") != "interiorPaint"
            or option.get("packageWeightKg") != 7
            or option.get("manufacturerProductCode") != "6000378"
            or option.get("manufacturerRoomUse") != "dry_and_humid"
            or option.get("status") != "not_configured_not_approved"
            or not _manufacturer_url(option.get("manufacturerUrl"))
            or not _valid_shop_url(option.get("secondShopUrl"))):
        raise ValueError("Unverified alternative product or source")
    if any("euroton eco" in str(source.get("name", "")).casefold()
           for source in configured):
        raise ValueError("Research-only alternative must not be configured for collection")
    alt_min, alt_max = _range(option)
    alt_app, alt_coats, _ = norm_by_key["interiorPaint"]
    alternative = {
        "replacesCandidateId": option["replacesCandidateId"],
        "name": option.get("name"),
        "manufacturerProductCode": option["manufacturerProductCode"],
        "manufacturerUrl": option["manufacturerUrl"],
        "independentShopUrlForReview": option["secondShopUrl"],
        "manufacturerKgPerM2ForConfiguredCoats": {
            "minimum": round(alt_min * alt_coats, 4),
            "maximum": round(alt_max * alt_coats, 4)},
        "appPreliminaryKgPerM2": alt_app,
        "compatibleConsumptionCandidate": (alt_min * alt_coats <= alt_app <= alt_max * alt_coats),
        "manufacturerRoomUse": option["manufacturerRoomUse"],
        "roomCoverageCompatibleWithGenericTier": True,
        "configuredForCollection": False,
        "approvedForPublication": False,
    }
    blocked = [row for row in results if row["requiresConsumptionReview"]]
    return {
        "schemaVersion": 1,
        "status": "technical_research_only",
        "country": "MD",
        "currency": "MDL",
        "technicalEvidenceReviewDate": evidence["reviewDate"],
        "appNormSourceNeedsReleaseRecheck": True,
        "summary": {
            "reviewedProducts": len(results),
            "preliminaryConsumptionCompatible": len(results) - len(blocked),
            "consumptionReviewRequired": len(blocked),
            "paintCandidatesDryRoomOnly": sum(
                row["manufacturerRoomUse"] == "dry_only" for row in results),
            "paintCandidatesHumidRoomCapable": sum(
                row["manufacturerRoomUse"] == "dry_and_humid" for row in results),
            "unapprovedAlternatives": 1,
        },
        "products": results,
        "alternativeForHumanResearch": alternative,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "automaticTierApprovalEnabled": False,
    }


def markdown(report):
    lines = ["# COSTARO — проверка расхода по документации производителя", "",
             "**Только исследование. Цены и формулы Flutter не менялись.**", "",
             "Нормы COSTARO — предварительные, проверенные по снимку кода "
             "`lib/data/material_norms.dart` от 02.11.2026. "
             "Перед релизом снимок нужно сверить с текущим Flutter-кодом.", "",
             "Один общий товар `interiorPaint` используется в приложении и для сухих, "
             "и для влажных помещений; технические ограничения производителя "
             "проверяются отдельно от расхода и цены.", "",
             "| Товар | Предварительная норма, кг/м² | Производитель, кг/м² | "
             "Упаковок на 50 м²: COSTARO / возможный диапазон | Расход | Применение |",
             "|---|---:|---:|---:|---|---|"]
    for row in report["products"]:
        spread = row["manufacturerKgPerM2ForConfiguredCoats"]
        packs = row["examplePackages"]
        lines.append(
            f"| `{row['id']}` | {row['appPreliminaryKgPerM2']:.2f} | "
            f"{spread['minimum']:.3f}–{spread['maximum']:.3f} | "
            f"{packs['appPreliminary']} / "
            f"{packs['manufacturerMinimum']}–{packs['manufacturerMaximum']} | "
            f"{row['status']} | {row['roomCoverageStatus']} |"
        )
    alt = report["alternativeForHumanResearch"]
    lines.extend(["", "## Выводы и ограничения", "",
                  "- Meșterul Manole: диапазон расхода слишком широк, "
                  "поэтому число упаковок требует уточнения по поверхности.",
                  "- Sansiro: нейтральная норма для двух слоёв ниже "
                  "минимального расхода производителя; не утверждать "
                  "его как универсальную премиальную краску.",
                  "- Romanita разрешена производителем только в сухих помещениях. "
                  "Она не может представлять универсальную бюджетную краску "
                  "для всех типов комнат (в том числе ванной) в текущем Flutter.",
                  "- Euroton Lav и Sansiro по заявленному назначению подходят "
                  "для влажных помещений, но это ещё не подтверждение "
                  "качества, свежей цены, нормы расхода или уровня цен.",
                  f"- Альтернатива для исследования: {alt['name']} "
                  "(артикул производителя " + alt["manufacturerProductCode"] + "). "
                  "Фасовка и расход предварительно сопоставимы, "
                  "производитель допускает влажные помещения, но две "
                  "независимые строгие цены и качество не утверждены.",
                  "- Ни один товар не получает автоматического утверждения "
                  "уровня budget/standard/premium только по расходу или цене.",
                  "- Для шпаклёвки здесь сравнивается только "
                  "`finishPuttyKgPerM2` **на стенах**. Предварительная "
                  "подготовка потолка использует другую норму и в этот "
                  "отчёт не включена.", "",
                  "## Официальные источники", ""])
    for row in report["products"]:
        lines.append(f"- `{row['id']}`: {row['manufacturerUrl']}")
    lines.append(f"- Альтернативный товар: {alt['manufacturerUrl']}")
    lines.append(f"- Независимый магазин (для дальнейшей проверки): "
                 f"{alt['independentShopUrlForReview']}")
    lines.append("")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--baseline", type=Path, default=Path("app_embedded_baseline.json"))
    parser.add_argument("--sources", type=Path, default=Path("price_sources.json"))
    parser.add_argument("--evidence", type=Path, default=Path("material_consumption_evidence.json"))
    parser.add_argument("--report", type=Path, default=Path("consumption_alignment_report.json"))
    parser.add_argument("--markdown", type=Path, default=Path("consumption_alignment_RU.md"))
    args = parser.parse_args(argv)
    input_paths = {p.resolve() for p in (args.catalog, args.baseline, args.sources,
                                         args.evidence)}
    if (args.report.resolve() in input_paths or args.markdown.resolve() in input_paths
            or args.report.resolve() == args.markdown.resolve()):
        raise ValueError("Report path cannot overwrite any source")
    if args.report.exists() or args.markdown.exists():
        raise FileExistsError("Consumption report already exists; refuse overwrite")
    result = audit(load(args.catalog), load(args.baseline), load(args.sources),
                   load(args.evidence))
    args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                      allow_nan=False) + "\n", encoding="utf-8")
    args.markdown.write_text(markdown(result), encoding="utf-8")
    print("=== COSTARO MANUFACTURER CONSUMPTION REVIEW ===")
    print("Reviewed:", result["summary"]["reviewedProducts"])
    print("Needs consumption review:", result["summary"]["consumptionReviewRequired"])
    print("Published prices and Flutter calculations were NOT changed.")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, OSError) as error:
        print("COSTARO CONSUMPTION AUDIT ERROR:", error, file=sys.stderr)
        raise SystemExit(2) from error
