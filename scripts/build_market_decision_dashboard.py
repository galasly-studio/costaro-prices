#!/usr/bin/env python3
"""Combined read-only material/labor market evidence decision dashboard.

Product-scoped retail prices and matching packages are research leads only.
No automatic quality tiers, price publication, or calculation changes.
"""

from __future__ import annotations

import json
import os
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


STRONG_METHODS = frozenset({
    "product_microdata",
    "product_structured_sku",
})

TIERS = ("budget", "standard", "premium")


def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def indexed(rows, key):
    result = {}

    for row in rows:
        item_key = row[key]

        if item_key in result:
            raise ValueError(f"Duplicate identifier: {item_key}")

        result[item_key] = row

    return result


def evaluate(
    catalog,
    observations,
    material_audit,
    pack_audit,
    labor_audit,
    labor_quotes,
    criteria_report,
    release_readiness,
):
    material_catalog = catalog["materialPrices"]
    labor_catalog = catalog["laborPrices"]

    if len(material_catalog) != 41 or len(labor_catalog) != 37:
        raise ValueError("Expected 41 materials and 37 labor rates")

    if catalog["country"] != "MD" or catalog["currency"] != "MDL":
        raise ValueError("Unexpected market or currency")

    if observations["currency"] != "MDL":
        raise ValueError("Observation currency does not match the catalog")

    if (
        release_readiness["status"] != "held"
        or release_readiness["explicitPublicationApproved"]
    ):
        raise ValueError("Publication state changed: explicit review required")

    profile_by_key = indexed(
        criteria_report["allMaterialProfiles"],
        "catalogMaterialKey",
    )

    if set(profile_by_key) != set(material_catalog):
        raise ValueError("Stage 40 criteria do not cover the complete catalog")

    if any(
        item["qualityTierApproved"] or item["approvedForPublication"]
        for item in profile_by_key.values()
    ):
        raise ValueError("Unexpected technical or publication approval")

    observed_by_id = indexed(observations["materials"], "id")
    audited_by_id = indexed(material_audit["materials"], "id")
    packed_by_id = indexed(pack_audit["products"], "id")

    if not (
        set(observed_by_id)
        == set(audited_by_id)
        == set(packed_by_id)
    ):
        raise ValueError("Material observation and pack audit IDs differ")

    grouped = defaultdict(list)
    strict_groups = []
    all_groups = []

    strong_observation_count = 0
    total_observation_count = 0

    for product_id in sorted(observed_by_id):
        observed = observed_by_id[product_id]
        audited = audited_by_id[product_id]
        packed = packed_by_id[product_id]

        key = audited["catalogMaterialKey"]

        if (
            packed["catalogMaterialKey"] != key
            or key not in material_catalog
        ):
            raise ValueError("Material mapping mismatch")

        if audited.get("verifiedForPublication"):
            raise ValueError("Market candidate was marked as published")

        if packed.get("approvedForPublication") or packed.get("reviewedTier"):
            raise ValueError("Unapproved material tier mapping detected")

        records = observed["observations"]
        total_observation_count += len(records)

        strong = [
            row
            for row in records
            if (
                row.get("status") == "candidate"
                and row.get("extractionMethod") in STRONG_METHODS
                and isinstance(row.get("price"), (int, float))
                and not isinstance(row.get("price"), bool)
                and row["price"] > 0
                and row.get("productCode")
            )
        ]

        strong_observation_count += len(strong)

        independent_stores = sorted({
            str(row["store"]).strip().casefold()
            for row in strong
        })

        exact_pack_tiers = [
            tier
            for tier in TIERS
            if packed["tierChecks"][tier]["status"] == "exact"
        ]

        blockers = []

        if not audited["comparisonReady"]:
            blockers.append("insufficient_comparable_market_sources")

        if len(independent_stores) < 2:
            blockers.append("fewer_than_two_product_scoped_store_prices")

        if packed["retailSkuMissing"]:
            blockers.append("retail_sku_missing")

        if not packed["twoShopMetadataPresent"]:
            blockers.append("two_shop_pack_metadata_missing")

        if not packed["marketComparisonReady"]:
            blockers.append("product_pack_market_comparison_not_ready")

        if not exact_pack_tiers:
            blockers.append("no_exact_catalog_package_alignment")

        eligible = not blockers

        row = {
            "observationId": product_id,
            "catalogMaterialKey": key,
            "status": (
                "two_shop_exact_pack_research_candidate"
                if eligible
                else "requires_more_research"
            ),
            "independentProductScopedStores": independent_stores,
            "productScopedPriceObservations": len(strong),
            "exactPackageTierSlots": exact_pack_tiers,
            "sourceBlockers": blockers,
            "researchMedianMDL": (
                statistics.median(x["price"] for x in strong)
                if eligible
                else None
            ),
            "retailerPriceResearchOnly": [
                {
                    "store": row["store"],
                    "url": row["url"],
                    "productCode": row["productCode"],
                    "displayedPriceMDL": row["price"],
                    "extractionMethod": row["extractionMethod"],
                }
                for row in strong
            ],
            "exactProductIdentityIndependentlyApproved": False,
            "qualityTierApproved": False,
            "priceDateVerified": False,
            "approvedForPublication": False,
        }

        all_groups.append(row)
        grouped[key].append(row)

        if eligible:
            strict_groups.append(row)

    material_rows = []
    queue = []

    for key in sorted(material_catalog):
        groups = grouped.get(key, [])

        candidates = [
            row
            for row in groups
            if row["status"] == "two_shop_exact_pack_research_candidate"
        ]

        if not groups:
            status = "source_monitoring_missing"
            priority = 1
            action = (
                "Настроить источники конкретного товара, упаковки и "
                "двух независимых продавцов Молдовы."
            )
        elif not candidates:
            status = "source_or_pack_evidence_incomplete"
            priority = 2
            action = (
                "Устранить несоответствия источников, артикула, "
                "упаковки или способа извлечения цены."
            )
        else:
            status = "product_price_research_ready_for_manual_identity"
            priority = 3
            action = (
                "Подтвердить идентичность артикула и упаковки, "
                "дату цены, техническое качество и затем вручную "
                "утвердить соответствие бюджет/стандарт/премиум."
            )

        material_rows.append({
            "catalogMaterialKey": key,
            "status": status,
            "observedProductGroups": len(groups),
            "strictResearchCandidateGroups": len(candidates),
            "candidateObservationIds": [
                item["observationId"]
                for item in candidates
            ],
            "publishedPricesChanged": False,
            "qualityTierApproved": False,
            "approvedForPublication": False,
        })

        queue.append({
            "kind": "material",
            "key": key,
            "priority": priority,
            "status": status,
            "nextActionRu": action,
            "approvedForPublication": False,
        })

    labor_by_key = indexed(labor_audit["rows"], "key")

    if set(labor_by_key) != set(labor_catalog):
        raise ValueError("Labor audit does not match 37 catalog rates")

    labor_quotes_by_key = defaultdict(list)

    for quote in labor_quotes["observations"]:
        if quote.get("status") == "research_quote":
            labor_quotes_by_key[quote["workKey"]].append(quote)

    labor_rows = []

    for key in sorted(labor_catalog):
        work = labor_by_key[key]
        quotes = labor_quotes_by_key.get(key, [])

        aligned = [
            quote
            for quote in quotes
            if quote.get("scopeStatus") == "preliminarily_aligned"
        ]

        comparable = work["status"] == "COMPARISON READY"

        labor_rows.append({
            "workKey": key,
            "status": (
                "reference_comparison_ready_not_live_verified"
                if comparable
                else "more_independent_scope_evidence_needed"
            ),
            "independentReferenceSources": work["independentSources"],
            "researchQuoteRows": len(quotes),
            "preliminarilyScopeAlignedQuoteRows": len(aligned),
            "liveRateDateVerified": False,
            "scopeIndependentlyApproved": False,
            "approvedForPublication": False,
        })

        queue.append({
            "kind": "labor",
            "key": key,
            "priority": 4 if not comparable else 5,
            "status": work["status"],
            "nextActionRu": (
                "Найти две актуальные независимые расценки, "
                "подтвердить единицу, технологию, толщину, "
                "количество слоёв, объём работы и дату цены."
            ),
            "approvedForPublication": False,
        })

    queue.sort(key=lambda item: (
        item["priority"],
        item["kind"],
        item["key"],
    ))

    summary = {
        "catalogMaterials": len(material_rows),
        "catalogLaborRates": len(labor_rows),
        "monitoredProductGroups": len(all_groups),
        "retailerPriceObservations": total_observation_count,
        "productScopedPriceObservations": strong_observation_count,
        "twoShopExactPackResearchGroups": len(strict_groups),
        "materialsWithStrictResearchCandidates": sum(
            row["strictResearchCandidateGroups"] > 0
            for row in material_rows
        ),
        "materialsWithoutMonitoring": sum(
            row["status"] == "source_monitoring_missing"
            for row in material_rows
        ),
        "previouslyReportedComparableTierSlots": (
            pack_audit["summary"][
                "catalogTierSlotsWithLiveComparableExactPacks"
            ]
        ),
        "laborReferenceComparisonReady": sum(
            row["status"] == "reference_comparison_ready_not_live_verified"
            for row in labor_rows
        ),
        "laborRequiringMoreEvidence": sum(
            row["status"] == "more_independent_scope_evidence_needed"
            for row in labor_rows
        ),
        "individualResearchDecisions": len(queue),
        "qualityTiersApproved": 0,
        "materialPricesApprovedForPublication": 0,
        "laborRatesApprovedForPublication": 0,
    }

    report = {
        "schemaVersion": 1,
        "status": "joint_market_evidence_workboard_read_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "priceCandidatesMustNotBeUsedAsCatalogTierPrices": True,
        "summary": summary,
        "strictRetailResearchGroups": strict_groups,
        "allRetailProductGroups": all_groups,
        "materials": material_rows,
        "labor": labor_rows,
    }

    decisions = {
        "schemaVersion": 1,
        "status": "human_research_actions_only",
        "approvedForPublication": False,
        "summary": {
            "materialDecisions": len(material_rows),
            "laborDecisions": len(labor_rows),
            "totalDecisions": len(queue),
            "approved": 0,
        },
        "items": queue,
    }

    return report, decisions


def markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — единая проверка материалов и работ",
        "",
        "**Исследовательский отчёт. Не разрешает изменять цены.**",
        "",
        f"- Материалов: **{summary['catalogMaterials']}**.",
        f"- Расценок работ: **{summary['catalogLaborRates']}**.",
        f"- Ценовых наблюдений: **{summary['retailerPriceObservations']}**.",
        f"- Товарно-привязанных наблюдений: **{summary['productScopedPriceObservations']}**.",
        f"- Групп с двумя магазинами и точной упаковкой: **{summary['twoShopExactPackResearchGroups']}**.",
        f"- Материалов с такими группами: **{summary['materialsWithStrictResearchCandidates']}**.",
        f"- Материалов без мониторинга: **{summary['materialsWithoutMonitoring']}**.",
        f"- Работ с предварительно сопоставимыми источниками: **{summary['laborReferenceComparisonReady']}**.",
        f"- Работ с недостаточными доказательствами: **{summary['laborRequiringMoreEvidence']}**.",
        "- Утверждённых категорий качества: **0**.",
        "- Разрешённых изменений цен: **0**.",
        "",
        "## Товарные группы для дальнейшей проверки",
        "",
        "| Группа товара | Магазинов | Предварительная медиана, MDL | Состояние |",
        "|---|---:|---:|---|",
    ]

    for item in report["strictRetailResearchGroups"]:
        lines.append(
            f"| `{item['observationId']}` "
            f"| {len(item['independentProductScopedStores'])} "
            f"| {item['researchMedianMDL']:.2f} "
            "| Только исследование |"
        )

    lines.extend([
        "",
        "Медианы отражают наблюдения магазинов для исследуемых товаров. ",
        "Их нельзя переносить в бюджет, стандарт или премиум без отдельной проверки.",
        "",
        "## Материалы каталога",
        "",
        "| Материал | Групп | Строгих кандидатов | Дальнейшее состояние |",
        "|---|---:|---:|---|",
    ])

    for item in report["materials"]:
        lines.append(
            f"| `{item['catalogMaterialKey']}` "
            f"| {item['observedProductGroups']} "
            f"| {item['strictResearchCandidateGroups']} "
            f"| `{item['status']}` |"
        )

    lines.extend([
        "",
        "## Работы",
        "",
        "| Работа | Справочных источников | Исследовательских строк | Статус |",
        "|---|---:|---:|---|",
    ])

    for item in report["labor"]:
        lines.append(
            f"| `{item['workKey']}` "
            f"| {item['independentReferenceSources']} "
            f"| {item['researchQuoteRows']} "
            f"| `{item['status']}` |"
        )

    lines.extend([
        "",
        "## Защитные ограничения",
        "",
        "- Два магазина ещё не доказывают идентичность товара и качество.",
        "- Строка расценки ещё не подтверждает полное совпадение состава работ.",
        "- Требуется подтверждение даты, упаковки, единицы и условий применения.",
        "- Нельзя автоматически выбирать качество товара по его цене.",
        "- Действующий каталог, формулы и нормы расхода сохранены.",
        "- Автоматическая публикация отключена.",
        "",
    ])

    return "\n".join(lines)


def main():
    report, queue = evaluate(
        load_json("prices.json"),
        load_json("price_observations.json"),
        load_json("price_audit_report.json"),
        load_json("material_pack_alignment_report.json"),
        load_json("labor_audit_report.json"),
        load_json("live_labor_quotes.json"),
        load_json("complete_material_criteria.json"),
        load_json("verified_release_readiness.json"),
    )

    Path("market_decision_dashboard.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    Path("market_decision_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    body = markdown(report)

    Path("market_decision_dashboard_RU.md").write_text(
        body,
        encoding="utf-8",
    )

    github_summary = os.environ.get("GITHUB_STEP_SUMMARY")

    if github_summary:
        with open(github_summary, "a", encoding="utf-8") as output:
            output.write(body + "\n")

    print("=== COSTARO STAGE 41 ===")

    for key, value in report["summary"].items():
        print(f"{key}: {value}")

    print("No catalog, quality-tier, norm or formula updates.")


if __name__ == "__main__":
    main()