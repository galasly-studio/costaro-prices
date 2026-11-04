"""Stage 48: inspect manufacturer/socket retail leads, never assign price tiers.

This is a deterministic, offline research memo. Historical page prices and store
stock badges are NOT live verification. No application/catalog files are edited.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


SAFE_FLAGS = (
    "publishedPricesChanged",
    "flutterCalculationsChanged",
    "consumptionNormsChanged",
    "automaticPublicationEnabled",
    "automaticTierAssignmentEnabled",
)

STORE_DOMAINS = {"Volta": "volta.md", "Gebhardt": "gebhardt.md", "Moldcablu": "moldcablu.md"}
PAGE_KINDS = {"exact_product_page", "category_card"}
LIFECYCLE_SIGNALS = {
    "no_discontinuation_notice_in_reviewed_page",
    "regional_discontinuation_notice_2023_02_02",
}


def safe_url(url, host, mpn=None):
    if not isinstance(url, str):
        return False
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname != host or parsed.username or parsed.password:
        return False
    if parsed.query or parsed.fragment:
        return False
    if mpn and f"/product/{mpn}/" not in parsed.path:
        return False
    return True


def build(pilot, research, catalog, policy, readiness):
    if any(pilot.get(key) is not False for key in SAFE_FLAGS):
        raise ValueError("Stage47 security flags changed")
    summary = pilot.get("summary", {})
    if (pilot.get("status") != "pilot_human_decision_dossiers_only"
            or summary.get("catalogMaterials") != 41
            or summary.get("strictResearchProductGroups") != 23
            or summary.get("technicalAndSourceConsistentResearchLeadsNotApproved") != 11
            or summary.get("firstHumanPilotDossiers") != 5
            or summary.get("approvedTierMappings") != 0
            or summary.get("approvedPriceChanges") != 0):
        raise ValueError("Unexpected Stage47 counts or approval status")
    if (catalog.get("status") != "draft"
            or catalog.get("automaticUpdatesEnabled") is not False
            or len(catalog.get("materialPrices", {})) != 41
            or policy.get("enabled") is not False
            or policy.get("approvedMappings") != []
            or readiness.get("status") != "held"
            or readiness.get("policyEnabled") is not False
            or readiness.get("explicitPublicationApproved") is not False
            or readiness.get("approvedMappingCount") != 0
            or readiness.get("proposedPriceChanges") != 0):
        raise ValueError("Catalog release state was modified")
    for item in pilot.get("allResearchLeads", []):
        if (item.get("approvedTier") is not None
                or item.get("budgetStandardPremiumMappingApproved") is not False
                or item.get("approvedPriceChange") is not False
                or item.get("autoPublicationAllowed") is not False):
            raise ValueError("Stage47 contains a pre-approved research item")
    existing = {x["catalogMaterialKey"]: x for x in pilot["allResearchLeads"]}
    if len(existing) != len(pilot["allResearchLeads"]):
        raise ValueError("Duplicate Stage47 research material")
    reference = existing.get("electricalSocketPerPiece")
    if (not reference or not reference.get("selectedForFirstHumanReview")
            or not any("EPH2900221" in src["productUrl"].upper()
                       for src in reference.get("retailResearchNotForCatalog", []))):
        raise ValueError("Asfora Stage47 research anchor is missing")

    if (research.get("schemaVersion") != 1
            or research.get("status") != "human_review_research_leads_only"
            or research.get("dateMeansCurrentPriceVerified") is not False
            or research.get("catalogMaterialKey") != "electricalSocketPerPiece"
            or not research.get("notes")
            or len(research.get("models", [])) != 4):
        raise ValueError("Research sources are missing, changed, or falsely verified")
    if research["models"][0].get("officialUrl") != reference.get("companySourceLeadUrl"):
        raise ValueError("Stage48 Asfora manufacturer URL must match Stage47 anchor")

    seen_models = set()
    compared = []
    for source in research["models"]:
        mpn = source.get("mpn")
        if (not isinstance(mpn, str) or not mpn.isascii()
                or not mpn.isalnum() or mpn in seen_models):
            raise ValueError("Duplicate or invalid manufacturer part number")
        seen_models.add(mpn)
        if source.get("manufacturer") != "Schneider Electric":
            raise ValueError(f"Unexpected manufacturer for {mpn}")
        if not safe_url(source.get("officialUrl"), "www.se.com", mpn):
            raise ValueError(f"Official manufacturer link has wrong part number: {mpn}")
        lifecycle = source.get("manufacturerLifecycleSignal")
        if lifecycle not in LIFECYCLE_SIGNALS:
            raise ValueError(f"Unrecognized lifecycle signal for {mpn}")
        traits = source.get("technicalTraits") or {}
        if (traits.get("grounded2PPlusE") is not True
                or traits.get("shutters") is not True
                or traits.get("ratedAmperes") != 16
                or traits.get("retailerDeclaredVolts") != 250
                or traits.get("retailerDeclaredIp") != "IP20"
                or not traits.get("mountingPackage")):
            raise ValueError(f"Socket not comparable within stated indoor group: {mpn}")
        if (source.get("retailerDescriptionConflict") not in (True, False)
                or not source.get("researchNotesRu")):
            raise ValueError(f"Missing source discrepancy notes for {mpn}")
        seen_stores = set()
        store_leads = []
        for shop in source.get("retailLeads", []):
            name = shop.get("store")
            kind = shop.get("pageKind")
            if (name not in STORE_DOMAINS or name in seen_stores
                    or kind not in PAGE_KINDS
                    or shop.get("codeShown") != mpn
                    or not safe_url(shop.get("url"), STORE_DOMAINS[name])
                    or type(shop.get("priceSnapshotMDLNotVerified")) not in (int, float)
                    or shop["priceSnapshotMDLNotVerified"] <= 0
                    or shop.get("promotionSnapshot") not in (True, False)):
                raise ValueError(f"Invalid or mismatched retail lead for {mpn}")
            if kind == "exact_product_page" and mpn.lower() not in shop["url"].lower():
                raise ValueError(f"Exact-product link lacks matching part number: {mpn}")
            seen_stores.add(name)
            store_leads.append(dict(shop))
        if not store_leads:
            raise ValueError(f"No retailer evidence for {mpn}")

        flags = []
        if lifecycle == "regional_discontinuation_notice_2023_02_02":
            flags.append("manufacturer_regional_discontinuation_notice")
        if source["retailerDescriptionConflict"]:
            flags.append("retailer_grounding_or_frame_description_conflict")
        if len(store_leads) < 2:
            flags.append("second_moldova_retailer_missing")
        if sum(x["pageKind"] == "exact_product_page" for x in store_leads) < 2:
            flags.append("second_exact_retail_product_card_missing")
        if any(x["promotionSnapshot"] for x in store_leads):
            flags.append("temporary_promotion_present")
        if traits["mountingPackage"] != "complete_single_socket":
            flags.append("frame_and_total_installed_package_to_confirm")

        if "manufacturer_regional_discontinuation_notice" in flags or source["retailerDescriptionConflict"]:
            reviewRoute = "blocked_pending_product_status_and_specification_recheck"
        elif "second_moldova_retailer_missing" in flags:
            reviewRoute = "second_moldova_store_required"
        elif "second_exact_retail_product_card_missing" in flags:
            reviewRoute = "second_exact_retail_product_card_required"
        else:
            reviewRoute = "candidate_for_human_document_review_only"
        compared.append({
            "catalogMaterialKey": "electricalSocketPerPiece",
            "manufacturer": source["manufacturer"],
            "range": source["range"],
            "mpn": mpn,
            "officialManufacturerUrl": source["officialUrl"],
            "manufacturerLifecycleSignal": lifecycle,
            "technicalTraitsAsAdvertisedNotIndependentlyTested": dict(traits),
            "retailResearchSnapshotsOnly": store_leads,
            "retailerSiteCountNotIndependentOwnershipProof": len(store_leads),
            "exactRetailProductPageCount": sum(x["pageKind"] == "exact_product_page" for x in store_leads),
            "researchFlags": flags,
            "reviewRoute": reviewRoute,
            "manualReviewNotesRu": list(source["researchNotesRu"]),
            "independentTechnicalPerformanceTestVerified": False,
            "moldovaPhysicalStockAndPriceDateVerified": False,
            "installedPackageAndFrameCostVerified": False,
            "approvedTier": None,
            "approvedPriceChange": False,
            "autoPublicationAllowed": False,
        })
    if set(seen_models) != {"EPH2900221", "LMR5210001", "GSL000145", "NU303718"}:
        raise ValueError("Required research comparisons changed")

    return {
        "schemaVersion": 1,
        "status": "socket_quality_comparison_research_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "researchDateNotPriceDate": research["capturedResearchDate"],
        **{flag: False for flag in SAFE_FLAGS},
        "summary": {
            "catalogMaterialsUntouched": 41,
            "manufacturerPartNumbersCompared": len(compared),
            "modelsWithTwoMoldovaRetailSiteLeads": sum(x["retailerSiteCountNotIndependentOwnershipProof"] >= 2 for x in compared),
            "modelsWithTwoExactRetailProductPageLeads": sum(x["exactRetailProductPageCount"] >= 2 for x in compared),
            "modelsBlockedByStatusOrConflictingDescriptions": sum(x["reviewRoute"].startswith("blocked") for x in compared),
            "modelsEligibleForNextHumanDocumentReviewOnly": sum(x["reviewRoute"] == "candidate_for_human_document_review_only" for x in compared),
            "independentlyApprovedQualityTiers": 0,
            "verifiedLivePriceChanges": 0,
        },
        "rulesForAnyFutureTierApprovalRu": [
            "Сравнивать полный установленный комплект: механизм, рамку, монтаж и одинаковое назначение.",
            "Проверить официальную документацию по каждому MPN, статус производства и соответствие требованиям помещения.",
            "Подтвердить реальную дату цены и наличие, независимо проверить технические характеристики.",
            "Не присваивать Бюджет/Стандарт/Премиум по цене, дизайну или маркетинговой линейке.",
            "Для влажных помещений не переносить решение по IP20; отдельно проверять IP, монтаж и нормативы.",
            "Пока отсутствует независимая оценка ресурса и безопасности — категории качества не утверждать.",
        ],
        "models": compared,
    }


def write_reports(report):
    Path("socket_model_comparison.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    lines = [
        "# COSTARO — этап 48: сравнение моделей розеток для будущей сметы", "",
        "**Исследование, а не подбор готовых цен или утверждение уровня качества.**", "",
        "В рабочем каталоге цены, нормы расхода и расчёты не изменены. Все суммы ниже — ",
        "снимки страниц магазинов, дата актуальной продажи и наличие не проверены.", "",
    ]
    for row in report["models"]:
        traits = row["technicalTraitsAsAdvertisedNotIndependentlyTested"]
        lines += [f"## {row['range']} — `{row['mpn']}`", "",
                  f"- Производитель: {row['officialManufacturerUrl']}",
                  f"- По опубликованным описаниям: 2P+E, шторки, {traits['ratedAmperes']} А / "
                  f"{traits['retailerDeclaredVolts']} В, {traits['retailerDeclaredIp']}, "
                  f"комплектация: `{traits['mountingPackage']}`.",
                  f"- Маршрут проверки: `{row['reviewRoute']}`.",
                  "- Найденные розничные страницы (**не проверенные текущие цены**):"]
        for shop in row["retailResearchSnapshotsOnly"]:
            promo = ", акция/распродажа" if shop["promotionSnapshot"] else ""
            lines.append(f"  - {shop['store']}: {shop['priceSnapshotMDLNotVerified']:g} MDL{promo}; "
                         f"`{shop['pageKind']}` — {shop['url']}")
        if row["researchFlags"]:
            lines += ["- Требуют уточнения:"]
            lines += [f"  - `{flag}`" for flag in row["researchFlags"]]
        lines += [f"- {note}" for note in row["manualReviewNotesRu"]]
        lines += ["- **Категория качества: не утверждена; перенос цены в COSTARO запрещён.**", ""]
    lines += ["## Что необходимо до утверждения категории", ""]
    lines += [f"- [ ] {item}" for item in report["rulesForAnyFutureTierApprovalRu"]]
    Path("socket_model_comparison_RU.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as f:
            f.write("\n### COSTARO Stage 48 — исследование розеток\n\n")
            f.write(f"Артикулов: **{len(report['models'])}**, утверждённых классов качества: **0**, "
                    "изменений цен: **0**. Все спорные модели остаются на ручной проверке.\n\n")


def main():
    paths = {
        "pilot": "manual_sku_pilot_dossiers.json",
        "research": "socket_comparison_research_sources.json",
        "catalog": "prices.json",
        "policy": "material_update_policy.json",
        "readiness": "verified_release_readiness.json",
    }
    inputs = {k: json.loads(Path(v).read_text(encoding="utf-8")) for k, v in paths.items()}
    report = build(**inputs)
    write_reports(report)
    print("COSTARO STAGE 48:", json.dumps(report["summary"], ensure_ascii=False))
    print("Research only. No tiers, live price approvals, or Flutter changes.")


if __name__ == "__main__":
    main()
