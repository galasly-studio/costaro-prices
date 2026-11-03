#!/usr/bin/env python3
"""Batch exact-retailer-source and quality-evidence research gate.

No approval of products, quality tiers, catalog prices or consumption norms.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def index_unique(rows, key):
    result = {}

    for row in rows:
        value = row[key]

        if value in result:
            raise ValueError(f"Duplicate {key}: {value}")

        result[value] = row

    return result


def retailer_identity(row):
    return (
        str(row["store"]).strip().casefold(),
        str(row["productCode"]).strip(),
        str(row["url"]).strip(),
    )


def build(source_config, dashboard, criteria, price_audit):
    configured = index_unique(source_config["materials"], "id")

    all_products = index_unique(
        dashboard["allRetailProductGroups"],
        "observationId",
    )

    if set(configured) != set(all_products):
        raise ValueError("Configured products and market observations disagree")

    strict = dashboard["strictRetailResearchGroups"]

    strict_ids = [item["observationId"] for item in strict]

    if len(strict_ids) != len(set(strict_ids)):
        raise ValueError("Duplicate strict retail candidate")

    profiles = index_unique(
        criteria["allMaterialProfiles"],
        "catalogMaterialKey",
    )

    if len(profiles) != 41:
        raise ValueError("Expected complete coverage of 41 materials")

    if source_config.get("automaticPublicationEnabled"):
        raise ValueError("Automatic source publication unexpectedly enabled")

    candidates = []
    tasks = []

    for item in strict:
        product_id = item["observationId"]

        if product_id not in configured:
            raise ValueError("Unknown research product")

        if (
            item["status"]
            != "two_shop_exact_pack_research_candidate"
        ):
            raise ValueError("Candidate was not admitted by Stage 41")

        config = configured[product_id]
        material_key = item["catalogMaterialKey"]

        if config["catalogMaterialKey"] != material_key:
            raise ValueError("Source-to-catalog mapping mismatch")

        if config.get("priceTier") is not None:
            raise ValueError(
                "Unexpected tier assignment in unapproved source configuration"
            )

        if material_key not in profiles:
            raise ValueError("Missing technical profile")

        profile = profiles[material_key]

        if (
            profile["qualityTierApproved"]
            or profile["approvedForPublication"]
        ):
            raise ValueError("Unapproved technical profile changed")

        configured_sources = {
            retailer_identity(row)
            for row in config["sources"]
        }

        observed_sources = {
            retailer_identity(row)
            for row in item["retailerPriceResearchOnly"]
        }

        exact_trace = (
            len(observed_sources) >= 2
            and observed_sources.issubset(configured_sources)
        )

        domains = {
            urlsplit(row["url"]).hostname
            for row in item["retailerPriceResearchOnly"]
        }

        separate_domains = (
            len(domains) >= 2
            and None not in domains
        )

        source_urls_https = all(
            urlsplit(row["url"]).scheme == "https"
            for row in item["retailerPriceResearchOnly"]
        )

        source_identity_consistent = (
            exact_trace
            and separate_domains
            and source_urls_https
        )

        requirements = [
            {
                "criterionId": check["criterionId"],
                "criterionRu": check["criterionRu"],
                "objectiveEvidenceVerified": False,
            }
            for check in profile["technicalCriteria"]
        ]

        candidate = {
            "observationId": product_id,
            "catalogMaterialKey": material_key,
            "configuredProductName": config["name"],
            "configuredMatchTerms": config.get("matchTerms", []),
            "twoRetailSitesConfirmedInConfiguration": separate_domains,
            "configuredStoreAndCodeTraceConsistent": exact_trace,
            "httpsSourceUrls": source_urls_https,
            "researchSourceIdentityConsistent": source_identity_consistent,
            "retailSources": [
                {
                    "store": row["store"],
                    "url": row["url"],
                    "productCode": row["productCode"],
                    "displayedPriceMDLResearchOnly": row["displayedPriceMDL"],
                    "extractionMethod": row["extractionMethod"],
                }
                for row in item["retailerPriceResearchOnly"]
            ],
            "researchMedianMDLNotForCatalog": item["researchMedianMDL"],
            "technicalFamilyId": profile["technicalFamilyId"],
            "technicalRequirements": requirements,
            "manufacturerModelMatchIndependentlyVerified": False,
            "moldovaPhysicalStockVerified": False,
            "currentPriceDateIndependentlyVerified": False,
            "qualityTierApproved": False,
            "approvedForPublication": False,
        }

        candidates.append(candidate)

        tasks.append({
            "observationId": product_id,
            "catalogMaterialKey": material_key,
            "researchIdentityTraceConsistent": source_identity_consistent,
            "technicalRequirementsNeedingReview": len(requirements),
            "nextActionRu": (
                "Подтвердить точную модель и упаковку у обоих продавцов, "
                "найти применимую техническую документацию производителя, "
                "проверить область применения и сравнимые характеристики. "
                "Только после документального решения рассматривать "
                "утверждение качества и ценовой категории."
            ),
            "independentTechnicalEvidenceApproved": False,
            "qualityTierApproved": False,
            "approvedForPublication": False,
        })

    if len(candidates) != dashboard["summary"][
        "twoShopExactPackResearchGroups"
    ]:
        raise ValueError("Strict source coverage changed unexpectedly")

    total_without_monitoring = set(
        price_audit["uncoveredMaterialKeys"]
    )

    if not total_without_monitoring.issubset(set(profiles)):
        raise ValueError("Unknown uncovered catalog material")

    missing_tier = sum(
        item.get("priceTier") is None
        for item in source_config["materials"]
    )

    summary = {
        "configuredProductGroups": len(configured),
        "strictResearchCandidates": len(candidates),
        "candidatesWithConsistentTwoStoreTrace": sum(
            item["researchSourceIdentityConsistent"]
            for item in candidates
        ),
        "candidatesRequiringSourceCorrection": sum(
            not item["researchSourceIdentityConsistent"]
            for item in candidates
        ),
        "sourceGroupsWithoutApprovedQualityTier": missing_tier,
        "materialsWithoutActualPriceMonitoring": len(total_without_monitoring),
        "materialsNeedingMoreMarketEvidence": (
            len(profiles)
            - dashboard["summary"][
                "materialsWithStrictResearchCandidates"
            ]
        ),
        "independentlyVerifiedManufacturerModels": 0,
        "approvedQualityTiers": 0,
        "approvedPriceChanges": 0,
    }

    report = {
        "schemaVersion": 1,
        "status": "bulk_exact_source_traceability_research_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "summary": summary,
        "unmonitoredMaterialKeys": sorted(total_without_monitoring),
        "candidates": candidates,
    }

    queue = {
        "schemaVersion": 1,
        "status": "manual_exact_sku_and_quality_evidence_review",
        "approvedForPublication": False,
        "summary": {
            "productGroups": len(tasks),
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "items": tasks,
    }

    return report, queue


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — проверка 23 товарных групп",
        "",
        "Проверка источников и доказательств. Не утверждение цен.",
        "",
        f"- Исследовательских товарных групп: **{summary['strictResearchCandidates']}**.",
        f"- С согласованными магазинами, ссылками и артикулами: **{summary['candidatesWithConsistentTwoStoreTrace']}**.",
        f"- Требующих исправления источников: **{summary['candidatesRequiringSourceCorrection']}**.",
        f"- Групп без утверждённой категории качества: **{summary['sourceGroupsWithoutApprovedQualityTier']}**.",
        f"- Материалов без фактического мониторинга: **{summary['materialsWithoutActualPriceMonitoring']}**.",
        f"- Материалов без строгой пары рыночных наблюдений: **{summary['materialsNeedingMoreMarketEvidence']}**.",
        "- Независимо подтверждённых моделей производителя: **0**.",
        "- Утверждённых категорий качества: **0**.",
        "- Разрешённых изменений цен: **0**.",
        "",
        "## Товарные группы и источники",
        "",
        "| Товар | Сайтов | Согласованность источников | Технических требований |",
        "|---|---:|---|---:|",
    ]

    for candidate in report["candidates"]:
        lines.append(
            f"| `{candidate['observationId']}` "
            f"| {len(candidate['retailSources'])} "
            f"| {'Да' if candidate['researchSourceIdentityConsistent'] else 'Требует исправления'} "
            f"| {len(candidate['technicalRequirements'])} |"
        )

    lines.extend([
        "",
        "## Что ещё обязательно подтвердить",
        "",
        "1. Точный товар и упаковку, а не только совпадение ссылок и артикула магазина.",
        "2. Техническую документацию производителя именно для выбранной модели.",
        "3. Применимость в выбранных помещениях и технологиях COSTARO.",
        "4. Сопоставимые эксплуатационные характеристики для оценки качества.",
        "5. Актуальность цены и возможность приобретения товара в Молдове.",
        "6. Отдельное документированное решение для категории качества.",
        "",
        "Ни один пункт не даёт автоматического разрешения на обновление каталога.",
        "",
        "## Отсутствующий мониторинг",
        "",
    ])

    for key in report["unmonitoredMaterialKeys"]:
        lines.append(f"- `{key}`")

    lines.extend([
        "",
        "**Цены, нормы расхода, формулы и качество в приложении не изменены.**",
        "",
    ])

    return "\n".join(lines)


def main():
    report, queue = build(
        load("price_sources.json"),
        load("market_decision_dashboard.json"),
        load("complete_material_criteria.json"),
        load("price_audit_report.json"),
    )

    Path("bulk_sku_quality_evidence.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    Path("bulk_sku_quality_review_queue.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    markdown = render_markdown(report)

    Path("bulk_sku_quality_evidence_RU.md").write_text(
        markdown,
        encoding="utf-8",
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(markdown + "\n")

    print("=== COSTARO STAGE 42 ===")

    for key, value in report["summary"].items():
        print(f"{key}: {value}")

    print("No price, tier, norm, formula or publication changes.")


if __name__ == "__main__":
    main()