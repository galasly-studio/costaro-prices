"""Stage 47: small, fully traceable human SKU review pilot.

Only assembles existing research; it cannot assign budget/standard/premium,
verify dates or stock, publish catalog prices, or alter the mobile app.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit


PILOT_KEYS = (
    "startPutty",
    "primer",
    "grout",
    "tileAdhesive",
    "electricalSocketPerPiece",
)

SAFE_FLAGS = (
    "publishedPricesChanged",
    "flutterCalculationsChanged",
    "consumptionNormsChanged",
    "automaticPublicationEnabled",
    "automaticTierAssignmentEnabled",
)


def guarded(report, label):
    if not isinstance(report, dict):
        raise ValueError(f"Missing {label}")
    for field in SAFE_FLAGS:
        if report.get(field) is not False:
            raise ValueError(f"Unsafe {label} flag: {field}")


def index(rows):
    result = {}
    for row in rows:
        key = row["catalogMaterialKey"]
        if key in result:
            raise ValueError(f"Duplicate material key: {key}")
        result[key] = row
    return result


def build(catalog, retail, bulk, manufacturer, matrix, readiness, policy, market_audit):
    for name, report in (("stage42", bulk), ("stage44", manufacturer), ("stage45", matrix)):
        guarded(report, name)
    if (catalog.get("status") != "draft" or catalog.get("automaticUpdatesEnabled") is not False
            or len(catalog.get("materialPrices", {})) != 41):
        raise ValueError("Unexpected catalog publication state or material count")
    if retail.get("automaticPublicationEnabled") is not False:
        raise ValueError("Retail auto publication must remain disabled")
    if policy.get("enabled") is not False or policy.get("approvedMappings") != []:
        raise ValueError("Approval policy may not be populated by this step")
    if (readiness.get("status") != "held" or readiness.get("policyEnabled") is not False
            or readiness.get("explicitPublicationApproved") is not False
            or readiness.get("approvedMappingCount") != 0
            or readiness.get("proposedPriceChanges") != 0):
        raise ValueError("Catalog release readiness unexpectedly changed")
    if (market_audit.get("summary", {}).get("verifiedForPublication") != 0
            or market_audit.get("status") != "audit_only"):
        raise ValueError("Market observations have changed publication semantics")

    candidates = index(bulk.get("candidates", []))
    official = index(manufacturer.get("records", []))
    all_materials = index(matrix.get("materials", []))
    if len(candidates) != 23 or set(official) != set(candidates):
        raise ValueError("Stage42/44 research coverage changed")
    if set(all_materials) != set(catalog["materialPrices"]):
        raise ValueError("Stage45 catalog coverage changed")
    if len(PILOT_KEYS) != len(set(PILOT_KEYS)):
        raise ValueError("Duplicate pilot key")

    configured = {}
    for group in retail.get("materials", []):
        configured.setdefault(group["catalogMaterialKey"], []).append(group)

    eligible = []
    for key, candidate in sorted(candidates.items()):
        doc = official[key]
        item = all_materials[key]
        checks = doc.get("companyContentEvidence") or {}
        if not doc.get("contentReadStatus", "").startswith("text_extracted_"):
            continue
        if (not checks.get("modelFamilyMarkersPresent")
                or not checks.get("configuredPackageOrRatingMentioned")
                or checks.get("technicalRestrictionSignals")):
            continue
        if (not candidate.get("twoRetailSitesConfirmedInConfiguration")
                or not candidate.get("configuredStoreAndCodeTraceConsistent")
                or not candidate.get("httpsSourceUrls")
                or not candidate.get("researchSourceIdentityConsistent")):
            continue
        if (candidate.get("approvedForPublication") is not False
                or candidate.get("qualityTierApproved") is not False
                or doc.get("approvedQualityTier") is not None
                or doc.get("approvedPriceChange") is not False
                or item.get("approvedForPublication") is not False):
            raise ValueError(f"Unexpected preapproved candidate: {key}")

        sources = candidate.get("retailSources", [])
        if len(sources) != 2 or len({s["store"] for s in sources}) != 2:
            continue
        if not all(
            urlsplit(s.get("url", "")).scheme == "https"
            and urlsplit(s["url"]).hostname
            and s.get("productCode")
            and s.get("extractionMethod") in ("product_structured_sku", "product_microdata")
            for s in sources
        ):
            continue
        # Cross-check every research source URL against the source configuration;
        # store product codes may legitimately differ across stores.
        configured_pairs = {
            (source["store"], source["url"], str(source.get("productCode", "")))
            for group in configured.get(key, []) for source in group.get("sources", [])
        }
        if not all((s["store"], s["url"], str(s["productCode"])) in configured_pairs for s in sources):
            raise ValueError(f"Untraced retail source for {key}")

        requirements = candidate.get("technicalRequirements", [])
        if not requirements or any(x.get("objectiveEvidenceVerified") is not False for x in requirements):
            raise ValueError(f"Technical criteria unexpectedly approved for {key}")
        if (candidate.get("manufacturerModelMatchIndependentlyVerified") is not False
                or candidate.get("moldovaPhysicalStockVerified") is not False
                or candidate.get("currentPriceDateIndependentlyVerified") is not False):
            raise ValueError(f"Live candidate verification flag changed for {key}")

        eligible.append({
            "catalogMaterialKey": key,
            "configuredResearchProductName": candidate["configuredProductName"],
            "technicalFamilyId": candidate["technicalFamilyId"],
            "companySourceLeadUrl": doc["officialSourceLeadUrl"],
            "companyDocumentSha256": doc.get("contentSha256"),
            "companyTextMentionsFamilyNotExactSku": True,
            "companyTextMentionsPackageNotExactSku": True,
            "twoIndependentRetailerNamesConfigured": [s["store"] for s in sources],
            "retailResearchNotForCatalog": [{
                "store": s["store"],
                "productUrl": s["url"],
                "storeProductCode": s["productCode"],
                "researchPriceMDLNotVerified": s.get("displayedPriceMDLResearchOnly"),
                "extractionMethod": s["extractionMethod"],
            } for s in sources],
            "technicalCriteriaAwaitingIndependentReview": [x["criterionRu"] for x in requirements],
            "productExactSkuIndependentlyVerified": False,
            "priceDateIndependentlyVerified": False,
            "moldovaPhysicalStockVerified": False,
            "independentTechnicalPerformanceEvidenceVerified": False,
            "budgetStandardPremiumMappingApproved": False,
            "approvedTier": None,
            "approvedPriceChange": False,
            "autoPublicationAllowed": False,
            "manualDecisionRequired": True,
            "selectedForFirstHumanReview": key in PILOT_KEYS,
        })

    eligible_map = index(eligible)
    if not set(PILOT_KEYS).issubset(eligible_map):
        raise ValueError("One or more pilot products no longer meet minimal research gates")

    return {
        "schemaVersion": 1,
        "status": "pilot_human_decision_dossiers_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        **{field: False for field in SAFE_FLAGS},
        "summary": {
            "catalogMaterials": len(all_materials),
            "strictResearchProductGroups": len(candidates),
            "technicalAndSourceConsistentResearchLeadsNotApproved": len(eligible),
            "firstHumanPilotDossiers": len(PILOT_KEYS),
            "technicalCriteriaIndependentlyReviewed": 0,
            "approvedTierMappings": 0,
            "approvedPriceChanges": 0,
        },
        "firstPilotMaterialKeys": list(PILOT_KEYS),
        "allResearchLeads": eligible,
    }


def write_reports(report):
    Path("manual_sku_pilot_dossiers.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    s = report["summary"]
    lines = [
        "# COSTARO — этап 47: точные товары для ручного подтверждения", "",
        "**Это только проверяемые исследовательские кандидаты. Ничего не присвоено категориям бюджет/стандарт/премиум.**", "",
        f"- Все материалы: **{s['catalogMaterials']}**.",
        f"- Групп с точными исследовательскими ссылками: **{s['strictResearchProductGroups']}**.",
        f"- Без явных технических конфликтов и с упоминанием упаковки: **{s['technicalAndSourceConsistentResearchLeadsNotApproved']}**.",
        f"- Первый ручной пилот: **{s['firstHumanPilotDossiers']}** товаров.",
        "- Подтверждений актуальной даты цены, физического наличия, точного SKU и категории качества: **0**.",
        "- Публикация новых цен: **запрещена**.", "",
    ]
    leads = index(report["allResearchLeads"])
    for key in report["firstPilotMaterialKeys"]:
        x = leads[key]
        lines += [f"## `{key}` — {x['configuredResearchProductName']}", "",
                  f"- Ссылка компании: {x['companySourceLeadUrl']}",
                  "- Два магазина (цены для исследования, не для приложения):"]
        for src in x["retailResearchNotForCatalog"]:
            lines.append(f"  - {src['store']}, код `{src['storeProductCode']}`: "
                         f"{src['researchPriceMDLNotVerified']} MDL — {src['productUrl']}")
        lines += ["- Проверить технические требования:"]
        lines += [f"  - [ ] {requirement}" for requirement in x["technicalCriteriaAwaitingIndependentReview"]]
        lines += ["- [ ] Совпадение точной модели и упаковки на всех трёх источниках.",
                  "- [ ] Физическое наличие в Молдове и актуальная дата конкретной цены.",
                  "- [ ] Независимые доказательства класса качества, а не только маркетинговые описания.",
                  "- [ ] Решение человека по категории (или отказ от сопоставления).", ""]
    lines += ["## Ограничения", "",
              "- Не переносить исследовательские цены в `prices.json`.",
              "- Не считать слова компании независимыми испытаниями.",
              "- Не переносить уровень качества между разными продуктами одной семьи.",
              "- Не применять решения для сухих помещений к влажным без технического подтверждения.",
              "- Окончательное решение должно пройти отдельные тесты и процедуру публикации.", ""]
    Path("manual_sku_pilot_dossiers_RU.md").write_text("\n".join(lines), encoding="utf-8")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as f:
            f.write("\n### COSTARO Stage 47 — первый товарный пилот\n\n")
            f.write(f"Исследовательских кандидатов: **{s['technicalAndSourceConsistentResearchLeadsNotApproved']}**, "
                    f"ручных досье первого пилота: **{s['firstHumanPilotDossiers']}**, "
                    "подтверждённых для публикации: **0**.\n\n")


def main():
    files = {
        "catalog": "prices.json", "retail": "price_sources.json",
        "bulk": "bulk_sku_quality_evidence.json", "manufacturer": "manufacturer_content_evidence.json",
        "matrix": "material_decision_matrix.json", "readiness": "verified_release_readiness.json",
        "policy": "material_update_policy.json", "market_audit": "price_audit_report.json",
    }
    inputs = {key: json.loads(Path(path).read_text(encoding="utf-8")) for key, path in files.items()}
    report = build(**inputs)
    write_reports(report)
    print("COSTARO STAGE 47:", json.dumps(report["summary"], ensure_ascii=False))
    print("No prices, tiers, or application calculations changed.")


if __name__ == "__main__":
    main()
