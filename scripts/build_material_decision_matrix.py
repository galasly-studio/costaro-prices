"""Stage 45: one read-only, 41-material decision matrix.

Configured retailer references, company text and research prices are NOT
independent confirmation of an exact Moldova SKU or of a quality tier.
"""

import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


SAFETY_FLAGS = (
    "publishedPricesChanged",
    "flutterCalculationsChanged",
    "consumptionNormsChanged",
    "automaticPublicationEnabled",
    "automaticTierAssignmentEnabled",
)

RESTRICTION_LABELS = {
    "company_text_limits_product_to_dry_rooms": "Краска ограничена сухими помещениями",
    "regional_thickness_range_disagreement_10_60_vs_25_80":
        "Региональные данные о толщине слоя расходятся (10–60 / 25–80 мм)",
    "technogips_type_a_normal_humidity_room_review":
        "Плита Type A предназначена для нормальной влажности; проверить применимость к выбранному помещению",
}


def unique_by(rows, key, expected=None):
    mapped = {}
    for row in rows:
        value = row[key]
        if value in mapped:
            raise ValueError(f"Duplicate {key}: {value}")
        mapped[value] = row
    if expected is not None and set(mapped) != set(expected):
        raise ValueError(f"Coverage mismatch: {key}")
    return mapped


def _assert_guard(report, label):
    if not isinstance(report, dict):
        raise ValueError(f"Missing or malformed {label}")
    for key in SAFETY_FLAGS:
        if report.get(key) is not False:
            raise ValueError(f"Unsafe {label}: {key}")


def build(catalog, configured, criteria, research, content, readiness, policy):
    for label, data in (
        ("criteria", criteria), ("research", research), ("content", content)
    ):
        _assert_guard(data, label)
    if catalog.get("status") != "draft" or catalog.get("automaticUpdatesEnabled") is not False:
        raise ValueError("Initial catalog publication guard changed")
    if len(catalog.get("materialPrices", {})) != 41 or len(catalog.get("laborPrices", {})) != 37:
        raise ValueError("Unexpected approved catalog coverage")
    if configured.get("automaticPublicationEnabled") is not False:
        raise ValueError("Retail source automatic publication enabled")
    if policy.get("enabled") is not False or policy.get("approvedMappings") != []:
        raise ValueError("Tier policy unexpectedly enabled or approved")
    if readiness.get("status") != "held" or readiness.get("policyEnabled") is not False:
        raise ValueError("Release readiness is not held")
    if readiness.get("explicitPublicationApproved") is not False:
        raise ValueError("Publication approval flag changed")
    if any(readiness.get(field) != 0 for field in ("approvedMappingCount", "proposedPriceChanges")):
        raise ValueError("Release has approved changes; requires separate review")

    keys = set(catalog["materialPrices"])
    profiles = unique_by(criteria.get("allMaterialProfiles", []), "catalogMaterialKey", keys)
    candidates = unique_by(research.get("candidates", []), "catalogMaterialKey")
    documents = unique_by(content.get("records", []), "catalogMaterialKey", candidates)
    if len(candidates) != 23 or not set(candidates).issubset(keys):
        raise ValueError("Stage 42 strict retail candidate coverage changed")
    if criteria.get("summary", {}).get("catalogMaterials") != len(keys):
        raise ValueError("Technical criteria count differs from catalog")
    if content.get("summary", {}).get("approvedQualityTiers") != 0:
        raise ValueError("Unexpected manufacturer approval")
    if (research.get("summary", {}).get("approvedPriceChanges") != 0
            or research.get("approvedPriceChanges", 0) not in (0, False)):
        raise ValueError("Unexpected research price approval")

    store_groups = defaultdict(list)
    for item in configured.get("materials", []):
        key = item.get("catalogMaterialKey")
        if key not in keys:
            raise ValueError(f"Unknown configured retailer key: {key}")
        store_groups[key].append(item)
    if set(store_groups) != keys:
        raise ValueError("Retail configuration does not cover 41 catalog keys")

    unmonitored = set(research.get("unmonitoredMaterialKeys", []))
    if unmonitored - keys:
        raise ValueError("Unknown unmonitored key")

    decisions = []
    for key in sorted(keys):
        p = profiles[key]
        c = candidates.get(key)
        doc = documents.get(key)
        evidence = (doc or {}).get("companyContentEvidence") or {}
        restrictions = evidence.get("technicalRestrictionSignals") or []
        official_url = (doc or {}).get("officialSourceLeadUrl")
        read_status = (doc or {}).get("contentReadStatus")
        confirmed_stores = sorted({src["store"] for g in store_groups[key] for src in g.get("sources", [])})
        missing = []

        if key in unmonitored:
            missing.append("Настроить проверяемое наблюдение цены для этой позиции")
        if c is None:
            missing.append("Найти сопоставимый точный артикул и упаковку в двух независимых магазинах Молдовы")
        if c is not None and not official_url:
            missing.append("Найти официальный документ конкретной модели изготовителя")
        if official_url and not (read_status or "").startswith("text_extracted_"):
            missing.append("Получить читаемый текст официального документа (если PDF скан — сверить вручную)")
        if official_url and (read_status or "").startswith("text_extracted_"):
            if not evidence.get("modelFamilyMarkersPresent"):
                missing.append("Проверить семейство/номер модели непосредственно в документе изготовителя")
            if not evidence.get("configuredPackageOrRatingMentioned"):
                missing.append("Сверить точный размер, упаковку или номинал региональной версии товара")

        for signal in restrictions:
            missing.append("Устранить техническое противоречие: " + RESTRICTION_LABELS.get(signal, signal))

        pending = [x for x in p.get("technicalCriteria", []) if not x.get("independentlyVerified")]
        if not pending and p.get("qualityTierApproved") is False:
            raise ValueError(f"Unexpected criterion state: {key}")
        missing.append("Подтвердить точный SKU, дату цены, наличие в Молдове и требования технического профиля")
        missing.append("Получить отдельное одобрение класса бюджет/стандарт/премиум до любых изменений")

        if restrictions:
            priority = 1
            priority_reason = "technical_conflict"
        elif key in unmonitored:
            priority = 1
            priority_reason = "no_live_monitoring"
        elif c and official_url and not (read_status or "").startswith("text_extracted_"):
            priority = 2
            priority_reason = "official_content_unreadable"
        elif c and not official_url:
            priority = 2
            priority_reason = "official_model_source_missing"
        elif c and official_url and not evidence.get("configuredPackageOrRatingMentioned"):
            priority = 2
            priority_reason = "manufacturer_format_unmatched"
        elif c:
            priority = 3
            priority_reason = "exact_sku_and_technical_review_pending"
        else:
            priority = 4
            priority_reason = "two_store_sku_research_pending"

        if p.get("qualityTierApproved") is not False or p.get("approvedForPublication") is not False:
            raise ValueError(f"Unexpected approved technical profile: {key}")
        if c and (c.get("qualityTierApproved") is not False or c.get("approvedForPublication") is not False):
            raise ValueError(f"Unexpected approved retail research candidate: {key}")
        if doc and (doc.get("approvedQualityTier") is not None or doc.get("approvedPriceChange") is not False):
            raise ValueError(f"Unexpected approved manufacturer research: {key}")

        decisions.append({
            "catalogMaterialKey": key,
            "technicalFamilyId": p["technicalFamilyId"],
            "configuredRetailProductGroups": len(store_groups[key]),
            "configuredRetailStoresNotVerified": confirmed_stores,
            "twoStoreExactResearchCandidateNotApproved": c is not None,
            "researchProductName": (c or {}).get("configuredProductName"),
            "officialManufacturerSourceLead": official_url,
            "officialContentReadStatus": read_status,
            "companyTextMentionsModelFamilyNotVerified": bool(evidence.get("modelFamilyMarkersPresent")),
            "companyTextMentionsPackageNotVerified": bool(evidence.get("configuredPackageOrRatingMentioned")),
            "technicalRestrictionSignals": restrictions,
            "technicalCriteriaNotIndependentlyVerified": [x["criterionRu"] for x in pending],
            "researchPriceVerifiedForPublication": False,
            "exactRetailSkuIndependentlyVerified": False,
            "approvedQualityTier": None,
            "approvedForPublication": False,
            "manualReviewRequired": True,
            "priority": priority,
            "priorityReason": priority_reason,
            "nextRequiredActionsRu": missing,
        })

    summary = {
        "catalogMaterials": len(decisions),
        "technicalFamilies": len({x["technicalFamilyId"] for x in decisions}),
        "strictTwoStoreResearchCandidatesNotApproved": len(candidates),
        "withoutStrictTwoStoreResearchCandidates": len(keys) - len(candidates),
        "withoutLivePriceObservations": len(unmonitored),
        "officialCompanyDocumentLeads": sum(bool(x["officialManufacturerSourceLead"]) for x in decisions),
        "officialContentTextExtracted": sum((x["officialContentReadStatus"] or "").startswith("text_extracted_") for x in decisions),
        "companyTextMissingConfiguredFormat": sum(bool(x["officialManufacturerSourceLead"]) and
                                                 (x["officialContentReadStatus"] or "").startswith("text_extracted_") and
                                                 not x["companyTextMentionsPackageNotVerified"] for x in decisions),
        "criticalTechnicalConflictMaterials": sum(bool(x["technicalRestrictionSignals"]) for x in decisions),
        "materialsReadyForPublication": 0,
        "independentlyVerifiedExactRetailSkus": 0,
        "approvedQualityTiers": 0,
        "approvedPriceChanges": 0,
        "manualActionCountsByPriority": dict(sorted(Counter(x["priority"] for x in decisions).items())),
    }
    return {
        "schemaVersion": 1,
        "status": "all_41_manual_evidence_review_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        **{key: False for key in SAFETY_FLAGS},
        "catalogPublicationStatus": catalog["status"],
        "verifiedReleaseReadiness": "held",
        "summary": summary,
        "materials": decisions,
    }


def write_reports(report):
    Path("material_decision_matrix.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    ordered = sorted(report["materials"], key=lambda r: (r["priority"], r["catalogMaterialKey"]))
    Path("material_manual_actions.json").write_text(
        json.dumps({"status": "manual_review_only", "approvedForPublication": 0,
                    "items": [{"catalogMaterialKey": r["catalogMaterialKey"], "priority": r["priority"],
                               "priorityReason": r["priorityReason"],
                               "nextRequiredActionsRu": r["nextRequiredActionsRu"]} for r in ordered]},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    s = report["summary"]
    lines = [
        "# COSTARO — этап 45: матрица решений для всех 41 материалов", "",
        "**Только исследование.** Даже точное совпадение названия на двух сайтах и в документе изготовителя не утверждает товар, качество, цену или дату.", "",
        f"- Все материалы: **{s['catalogMaterials']}**; технических семейств: **{s['technicalFamilies']}**.",
        f"- Двухмагазинные кандидаты для ручной сверки: **{s['strictTwoStoreResearchCandidatesNotApproved']}**; без них: **{s['withoutStrictTwoStoreResearchCandidates']}**.",
        f"- Без фактического наблюдения цены: **{s['withoutLivePriceObservations']}**.",
        f"- Официальных ссылок: **{s['officialCompanyDocumentLeads']}**; текстов прочитано: **{s['officialContentTextExtracted']}**.",
        f"- Официальные тексты с отсутствующей упаковкой/номиналом: **{s['companyTextMissingConfiguredFormat']}**.",
        f"- Явных технических конфликтов: **{s['criticalTechnicalConflictMaterials']}**.",
        "- **Утверждено SKU: 0; категорий качества: 0; изменений цен: 0. Автопубликация отключена.**", "",
        "| Приоритет | Материал | Два магазина, кандидат | Документ | Критическая задача |",
        "|---:|---|---|---|---|",
    ]
    for item in ordered:
        doc = item["officialContentReadStatus"] or "нет официальной ссылки"
        action = item["nextRequiredActionsRu"][0].replace("|", "/")
        name = item["catalogMaterialKey"].replace("|", "/")
        candidate = "да, не утверждён" if item["twoStoreExactResearchCandidateNotApproved"] else "нет"
        lines.append(f"| {item['priority']} | `{name}` | {candidate} | `{doc}` | {action} |")
    lines += ["", "## Требования перед публикацией", "",
              "1. Проверить точный артикул, региональную модификацию, упаковку и наличие в Молдове.",
              "2. Отдельно проверить техническую пригодность, ограничения для помещений и критерии качества.",
              "3. Подтвердить цену и её дату независимо, затем вручную одобрить сопоставление с бюджет/стандарт/премиум.",
              "4. Не менять `prices.json`, нормы расхода, формулы Flutter и автоматическую публикацию без отдельной процедуры.", ""]
    Path("material_decision_matrix_RU.md").write_text("\n".join(lines), encoding="utf-8")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as f:
            f.write("\n### COSTARO Stage 45 — все 41 материалов\n\n")
            f.write(f"Кандидаты двух магазинов: **{s['strictTwoStoreResearchCandidatesNotApproved']}**, "
                    f"текстов производителей: **{s['officialContentTextExtracted']}**, "
                    "разрешённых изменений цены: **0**. Матрица и действия — в Artifact.\n\n")


def main():
    inputs = {
        "catalog": "prices.json",
        "configured": "price_sources.json",
        "criteria": "complete_material_criteria.json",
        "research": "bulk_sku_quality_evidence.json",
        "content": "manufacturer_content_evidence.json",
        "readiness": "verified_release_readiness.json",
        "policy": "material_update_policy.json",
    }
    data = {key: json.loads(Path(name).read_text(encoding="utf-8")) for key, name in inputs.items()}
    report = build(**data)
    write_reports(report)
    print("COSTARO STAGE 45:", json.dumps(report["summary"], ensure_ascii=False))
    print("READ ONLY — quality tiers and published prices unchanged, publication held.")


if __name__ == "__main__":
    main()
