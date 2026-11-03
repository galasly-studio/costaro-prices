#!/usr/bin/env python3
"""COSTARO Stage 31: quality-first research policy.

A product's quality tier must be supported by relevant technical
and comparative performance evidence. Retail price never establishes quality.

Research-only: this script cannot assign tiers or publish prices.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from validate_app_catalog import load


POLICY_VERSION = 1

UNIVERSAL_RULES = (
    "product_identity_and_pack_verified",
    "intended_use_technically_compatible",
    "consumption_and_units_checked",
    "objective_comparable_quality_evidence_required",
    "retail_price_is_not_quality_proof",
    "human_tier_approval_required",
)

DETAILED_CRITERIA = {
    "finishPutty": {
        "title": "Финишная шпаклёвка",
        "technicalFactors": [
            "Совместимость с основанием",
            "Допустимая толщина слоя",
            "Расход на квадратный метр",
            "Характеристики сцепления с основанием",
            "Стабильность покрытия и риск растрескивания",
            "Качество финишной поверхности",
        ],
        "missingObjectiveEvidence": [
            "Сопоставимые результаты испытаний адгезии или других "
            "существенных эксплуатационных характеристик",
            "Независимое подтверждение преимуществ перед "
            "сравниваемыми материалами",
            "Документированное обоснование выбранного уровня качества",
        ],
        "referenceStandard": "EN 16566",
    },
    "interiorPaint": {
        "title": "Интерьерная краска",
        "technicalFactors": [
            "Назначение для сухих и влажных помещений",
            "Стойкость к влажному истиранию",
            "Укрывистость при определённом расходе",
            "Расход для предусмотренного количества слоёв",
            "Тип покрытия и условия нанесения",
        ],
        "missingObjectiveEvidence": [
            "Подтверждённый класс стойкости к влажному "
            "истиранию по применимому методу испытаний",
            "Сопоставимые показатели укрывистости",
            "Сравнение характеристик с товарами "
            "той же области применения",
        ],
        "referenceStandard": "EN 13300",
    },
}


def index_products(rows, label):
    if not isinstance(rows, list):
        raise ValueError("Missing product list: " + label)

    result = {}

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid product in " + label)

        key = row.get("id")

        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Duplicate or invalid product ID: " + label)

        result[key] = row

    return result


def build(catalog, quality, traceability, *, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    if (
        catalog.get("country") != "MD"
        or catalog.get("currency") != "MDL"
        or not isinstance(catalog.get("materialPrices"), dict)
    ):
        raise ValueError("Invalid Moldova material catalog")

    if (
        quality.get("schemaVersion") != 1
        or quality.get("status") != "manufacturer_quality_research_only"
        or quality.get("publishedPricesChanged") is not False
        or quality.get("flutterCalculationsChanged") is not False
        or quality.get("tierMappingsChanged") is not False
    ):
        raise ValueError("Unsafe manufacturer quality report")

    if (
        traceability.get("schemaVersion") != 1
        or traceability.get("status") != "source_traceability_research_only"
        or traceability.get("publishedPricesChanged") is not False
        or traceability.get("flutterCalculationsChanged") is not False
        or traceability.get("tierMappingsChanged") is not False
    ):
        raise ValueError("Unsafe retailer traceability report")

    catalog_keys = set(catalog["materialPrices"])

    if not set(DETAILED_CRITERIA).issubset(catalog_keys):
        raise ValueError("Quality criteria reference unknown materials")

    quality_rows = index_products(quality.get("products"), "quality")
    source_rows = index_products(traceability.get("products"), "traceability")

    if set(quality_rows) != set(source_rows):
        raise ValueError("Manufacturer and retailer product IDs differ")

    if len(quality_rows) != 3:
        raise ValueError("Expected exactly three pilot products")

    products = []

    for product_id, product in quality_rows.items():
        source = source_rows[product_id]
        material_key = product.get("catalogMaterialKey")

        if material_key not in DETAILED_CRITERIA:
            raise ValueError(
                "Missing detailed criteria for pilot: " + product_id
            )

        if (
            source.get("catalogMaterialKey") != material_key
            or source.get("tierHintOnly")
               != product.get("tierHintForHumanReview")
        ):
            raise ValueError("Material identity mismatch: " + product_id)

        if (
            product.get("qualityTierVerified") is not False
            or product.get("approvedForPublication") is not False
            or source.get("qualityTierVerified") is not False
            or source.get("approvedForPublication") is not False
        ):
            raise ValueError("Unexpected quality or publication approval")

        if product.get("tierHintForHumanReview") not in (
            "budget", "standard", "premium"
        ):
            raise ValueError("Invalid research tier hint")

        criteria = DETAILED_CRITERIA[material_key]

        blockers = []

        if product.get("technicalPreliminaryMatch") is not True:
            blockers.append("technical_compatibility_needs_review")

        if source.get("fullyStructuredRetailMethods") is not True:
            blockers.append("retailer_identity_evidence_needs_review")

        if (
            source.get("retailObservationsFresh") is not True
            or source.get("manufacturerEvidenceFresh") is not True
        ):
            blockers.append("research_evidence_is_stale")

        blockers.append("objective_quality_comparison_missing")
        blockers.append("human_tier_approval_missing")

        products.append({
            "id": product_id,
            "catalogMaterialKey": material_key,
            "suggestedTierNotApproved":
                product["tierHintForHumanReview"],
            "referenceStandard": criteria["referenceStandard"],
            "technicalFactors": criteria["technicalFactors"],
            "requiredObjectiveEvidence":
                criteria["missingObjectiveEvidence"],
            "sourceScreeningStatus":
                source.get("sourceScreeningStatus"),
            "blockingReasons": blockers,
            "qualityTierApproved": False,
            "priceCanDetermineQualityTier": False,
            "approvedForPublication": False,
        })

    products.sort(key=lambda row: row["id"])

    materials = []

    for key in sorted(catalog_keys):
        detailed = key in DETAILED_CRITERIA

        materials.append({
            "catalogMaterialKey": key,
            "universalQualityFirstRulesApply": True,
            "detailedCriteriaStatus": (
                "pilot_defined" if detailed
                else "material_specific_criteria_pending"
            ),
            "automaticallyApproved": False,
        })

    return {
        "schemaVersion": 1,
        "policyVersion": POLICY_VERSION,
        "status": "quality_first_research_only",
        "generatedAt": now.isoformat(),
        "principle": {
            "qualityDeterminesTier": True,
            "verifiedMarketPriceDeterminesCost": True,
            "priceAloneMayNeverDetermineTier": True,
            "unverifiedQualityMustRemainUnclassified": True,
        },
        "universalRules": list(UNIVERSAL_RULES),
        "summary": {
            "catalogMaterialsCoveredByUniversalRule": len(materials),
            "materialGroupsWithDetailedPilotCriteria":
                len(DETAILED_CRITERIA),
            "materialGroupsAwaitingDetailedCriteria":
                len(materials) - len(DETAILED_CRITERIA),
            "pilotProductsReviewed": len(products),
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "materials": materials,
        "products": products,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
    }


def markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — этап 31: объективная оценка качества",
        "",
        "**Только исследование. Действующие цены и формулы сохранены.**",
        "",
        "## Утверждённый принцип",
        "",
        "**Качество определяет категорию. Подтверждённая "
        "рыночная цена определяет стоимость.**",
        "",
        "Цена товара сама по себе не доказывает его качество.",
        "",
        f"Материалов под универсальным правилом: "
        f"{summary['catalogMaterialsCoveredByUniversalRule']}.",
        f"Групп с детальными пилотными критериями: "
        f"{summary['materialGroupsWithDetailedPilotCriteria']}.",
        f"Групп, которым ещё нужны отдельные критерии: "
        f"{summary['materialGroupsAwaitingDetailedCriteria']}.",
        f"Утверждённых уровней качества: "
        f"{summary['qualityTiersApproved']}.",
        "",
        "| Материал | Подсказка уровня | Стандарт для проверки | Решение |",
        "|---|---|---|---|",
    ]

    for product in report["products"]:
        lines.append(
            f"| `{product['id']}` | "
            f"{product['suggestedTierNotApproved']} | "
            f"{product['referenceStandard']} | "
            "не утверждено |"
        )

    for material_key, criteria in DETAILED_CRITERIA.items():
        lines.extend([
            "",
            f"## {criteria['title']} — `{material_key}`",
            "",
            f"Ориентир для технического сравнения: "
            f"{criteria['referenceStandard']}.",
            "",
            "### Что сравниваем",
        ])

        for factor in criteria["technicalFactors"]:
            lines.append("- " + factor)

        lines.extend(["", "### Какие доказательства ещё нужны"])

        for evidence in criteria["missingObjectiveEvidence"]:
            lines.append("- " + evidence)

    lines.extend([
        "",
        "## Ограничения",
        "",
        "- Категории не присваиваются по цене.",
        "- Отсутствие независимых характеристик означает "
        "недостаточность доказательств.",
        "- Критерии остальных групп материалов требуют "
        "отдельной технической проработки.",
        "- Ни одна цена не разрешена к публикации.",
        "- Цены, нормы расхода и формулы COSTARO не менялись.",
        "",
    ])

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--catalog",
        type=Path,
        default=Path("prices.json"),
    )
    parser.add_argument(
        "--quality",
        type=Path,
        default=Path("material_quality_dossiers.json"),
    )
    parser.add_argument(
        "--traceability",
        type=Path,
        default=Path("material_source_traceability.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("material_quality_first_review.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("material_quality_first_review_RU.md"),
    )

    args = parser.parse_args()

    paths = [
        args.catalog.resolve(),
        args.quality.resolve(),
        args.traceability.resolve(),
        args.report.resolve(),
        args.markdown.resolve(),
    ]

    if len(set(paths)) != len(paths):
        raise ValueError("Input and output paths must be different")

    if args.report.exists() or args.markdown.exists():
        raise FileExistsError("Stage 31 report already exists")

    report = build(
        load(args.catalog),
        load(args.quality),
        load(args.traceability),
    )

    args.report.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
            allow_nan=False,
        ) + "\n",
        encoding="utf-8",
    )

    args.markdown.write_text(
        markdown(report),
        encoding="utf-8",
    )

    print("=== COSTARO STAGE 31: QUALITY FIRST ===")
    print(
        "Catalog materials:",
        report["summary"]["catalogMaterialsCoveredByUniversalRule"],
    )
    print(
        "Detailed pilot groups:",
        report["summary"]["materialGroupsWithDetailedPilotCriteria"],
    )
    print(
        "Tier approvals:",
        report["summary"]["qualityTiersApproved"],
    )
    print("Prices and Flutter calculations NOT changed.")


if __name__ == "__main__":
    main()