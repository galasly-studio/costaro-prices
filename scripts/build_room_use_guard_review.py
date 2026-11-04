"""Stage 46: guarded technical-use and format review of research evidence.

No application room behavior, catalog price, product tier, or publication state
is changed. The report is a human decision queue, not an automatic approval.
"""

import json
import os
from datetime import datetime, timezone
from pathlib import Path


TECHNICAL_WARNINGS = {
    "company_text_limits_product_to_dry_rooms": (
        "Краска Romanita: только сухие помещения по документации компании.",
        "Не назначать универсальную привязку для всех помещений; проверить правила комнат и альтернативы для влажных зон.",
    ),
    "regional_thickness_range_disagreement_10_60_vs_25_80": (
        "Kreisel 441: диапазоны толщины 10–60 и 25–80 мм различаются.",
        "Подтвердить точную региональную модификацию и применимые технические пределы перед любым сопоставлением.",
    ),
    "technogips_type_a_normal_humidity_room_review": (
        "Гипсокартон Technogips Type A: указан режим нормальной влажности.",
        "Уточнить тип помещения и допустимую влажность; не считать Type A универсальной влагостойкой плитой.",
    ),
}

COMPOSITE_KEY = "ceilingFrameFastenersPerM2"


def guard(report, name):
    if not isinstance(report, dict):
        raise ValueError("Missing report: " + name)
    for key in ("publishedPricesChanged", "flutterCalculationsChanged", "consumptionNormsChanged",
                "automaticPublicationEnabled", "automaticTierAssignmentEnabled"):
        if report.get(key) is not False:
            raise ValueError(f"Unsafe {name} flag: {key}")


def index(rows):
    found = {}
    for row in rows:
        key = row["catalogMaterialKey"]
        if key in found:
            raise ValueError("Duplicate material: " + key)
        found[key] = row
    return found


def build(matrix, content, catalog, retailer_sources):
    guard(matrix, "Stage45")
    guard(content, "Stage44")
    if matrix.get("status") != "all_41_manual_evidence_review_only":
        raise ValueError("Unknown Stage45 report")
    if catalog.get("status") != "draft" or catalog.get("automaticUpdatesEnabled") is not False:
        raise ValueError("Catalog state is not held")
    if retailer_sources.get("automaticPublicationEnabled") is not False:
        raise ValueError("Retail automatic publication is enabled")
    if len(catalog.get("materialPrices", {})) != 41:
        raise ValueError("Catalog material coverage changed")

    all_rows = index(matrix.get("materials", []))
    documents = index(content.get("records", []))
    if set(all_rows) != set(catalog["materialPrices"]) or len(documents) != 23:
        raise ValueError("Material coverage mismatch")
    if set(documents) - set(all_rows):
        raise ValueError("Unknown manufacturer material")
    for key, row in all_rows.items():
        if (row.get("approvedForPublication") is not False or
                row.get("exactRetailSkuIndependentlyVerified") is not False or
                row.get("approvedQualityTier") is not None):
            raise ValueError("Already-approved Stage45 row: " + key)

    warnings = []
    for key in sorted(documents):
        doc = documents[key]
        evidence = doc.get("companyContentEvidence") or {}
        for signal in evidence.get("technicalRestrictionSignals", []):
            if signal not in TECHNICAL_WARNINGS:
                raise ValueError(f"Unknown technical restriction requires manual update: {signal}")
            if signal not in all_rows[key].get("technicalRestrictionSignals", []):
                raise ValueError(f"Stage44/45 restriction mismatch: {key}")
            description, action = TECHNICAL_WARNINGS[signal]
            warnings.append({
                "catalogMaterialKey": key,
                "researchProductName": doc["configuredProductName"],
                "technicalSignal": signal,
                "officialSourceLeadUrl": doc["officialSourceLeadUrl"],
                "reasonRu": description,
                "nextManualActionRu": action,
                "notValidForEveryRoomUntilReviewed": True,
                "productIndependentlyVerified": False,
                "tierApproved": False,
                "approvedForPublication": False,
            })

    format_gaps = []
    for key, doc in sorted(documents.items()):
        evidence = doc.get("companyContentEvidence") or {}
        if doc.get("officialSourceLeadUrl") and doc.get("contentReadStatus", "").startswith("text_extracted_"):
            if not evidence.get("configuredPackageOrRatingMentioned"):
                format_gaps.append({
                    "catalogMaterialKey": key,
                    "researchProductName": doc["configuredProductName"],
                    "officialSourceLeadUrl": doc["officialSourceLeadUrl"],
                    "missingEvidenceRu": "В доступном тексте официальной страницы не найден точный размер/упаковка; сверить региональную позицию вручную.",
                    "exactRetailSkuIndependentlyVerified": False,
                    "approvedForPublication": False,
                })

    if COMPOSITE_KEY not in all_rows:
        raise ValueError("Unmonitored composite key missing")
    composite_source_rows = [x for x in retailer_sources.get("materials", [])
                             if x.get("catalogMaterialKey") == COMPOSITE_KEY]
    if len(composite_source_rows) != 1 or composite_source_rows[0].get("sources") != []:
        raise ValueError("Composite fastener source model changed")
    if all_rows[COMPOSITE_KEY]["priorityReason"] != "no_live_monitoring":
        raise ValueError("Composite fastener missing source guard")
    if not all(isinstance(catalog["materialPrices"][COMPOSITE_KEY].get(tier), (int, float))
               for tier in ("budget", "standard", "premium")):
        raise ValueError("Composite price shape changed")

    return {
        "schemaVersion": 1,
        "status": "manual_room_and_pack_review_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "summary": {
            "catalogMaterials": len(all_rows),
            "technicalRestrictionsRequiringHumanReview": len(warnings),
            "manufacturerFormatTextGaps": len(format_gaps),
            "compositePriceItemsWithoutDirectRetailSources": 1,
            "approvedForPublication": 0,
        },
        "roomUseWarnings": warnings,
        "manufacturerFormatGaps": format_gaps,
        "compositePricingReview": {
            "catalogMaterialKey": COMPOSITE_KEY,
            "configuredUnit": "MDL/m² (composite calculation, not a shop SKU)",
            "manualActionRu": (
                "Сначала подтвердить состав комплекта крепежа, количество каждого компонента на м², "
                "цену единиц и риск двойного учёта; не подставлять цену одного изделия вместо цены комплекта."
            ),
            "currentPricesPreserved": True,
            "normalizationOrAutoUpdateAllowed": False,
        },
    }


def write_reports(report):
    Path("room_and_pack_safety_review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    s = report["summary"]
    lines = [
        "# COSTARO — этап 46: ограничения по помещениям и упаковкам", "",
        "Все сведения из документов компаний — ориентиры для ручной проверки, а не одобрение цены или класса качества.", "",
        f"- Каталог: **{s['catalogMaterials']}** позиций.",
        f"- Ограничения применения, требующие решения: **{s['technicalRestrictionsRequiringHumanReview']}**.",
        f"- Не найден точный формат/упаковка в тексте изготовителя: **{s['manufacturerFormatTextGaps']}**.",
        "- Композитный крепёж потолка без прямого товарного SKU: **1**.",
        "- Разрешено менять цены: **0**. Автопубликация **выключена**.", "",
        "## Технические ограничения", "",
    ]
    for w in report["roomUseWarnings"]:
        lines += [f"- **`{w['catalogMaterialKey']}`**: {w['reasonRu']} "
                  f"Действие: {w['nextManualActionRu']}"]
    lines += ["", "## Нет точного формата в официальном тексте", ""]
    for gap in report["manufacturerFormatGaps"]:
        lines += [f"- **`{gap['catalogMaterialKey']}`** — {gap['researchProductName']}"]
    lines += ["", "## Композитная позиция", "", report["compositePricingReview"]["manualActionRu"], "",
              "Цены `prices.json`, нормы, расчёты Flutter и категории бюджет/стандарт/премиум не изменены.", ""]
    Path("room_and_pack_safety_review_RU.md").write_text("\n".join(lines), encoding="utf-8")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as f:
            f.write("\n### COSTARO Stage 46 — ограничения и упаковки\n\n")
            f.write(f"Ограничения: **{s['technicalRestrictionsRequiringHumanReview']}**, "
                    f"форматы под вопросом: **{s['manufacturerFormatTextGaps']}**. "
                    "Цены и уровни качества не изменены.\n\n")


def main():
    paths = {
        "matrix": "material_decision_matrix.json",
        "content": "manufacturer_content_evidence.json",
        "catalog": "prices.json",
        "retailer_sources": "price_sources.json",
    }
    inputs = {key: json.loads(Path(path).read_text(encoding="utf-8")) for key, path in paths.items()}
    report = build(**inputs)
    write_reports(report)
    print("COSTARO STAGE 46:", json.dumps(report["summary"], ensure_ascii=False))
    print("ALL PRICES, FORMULAS AND QUALITY TIERS HELD FOR REVIEW.")


if __name__ == "__main__":
    main()
