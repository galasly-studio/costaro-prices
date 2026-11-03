#!/usr/bin/env python3
"""Read-only review dossiers for six material candidates.

Neither source observations nor manufacturer consumption alone may approve
a budget/standard/premium tier or change the published COSTARO catalog.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

from validate_app_catalog import load

IDS = frozenset({
    "glet_mesterul_manole_8kg",
    "glet_b62_satroc_8kg",
    "glet_satroc_8kg",
    "romanita_7kg",
    "euroton_lav_7kg",
    "sansiro_7kg",
})

REASON_RU = {
    "consumption_review": "Уточнить расход и количество упаковок",
    "room_scope_incompatible": "Не подходит для универсального применения во всех комнатах",
    "sku_and_method_review": "Проверить артикул и метод извлечения цены",
    "retail_evidence_missing": "Получить свежие сопоставимые цены и подтвердить фасовку",
    "tier_quality_review": "Подтвердить качество и принадлежность к ценовому уровню",
}


def build(tiers, technical):
    if (
        not isinstance(tiers, dict)
        or tiers.get("schemaVersion") != 1
        or tiers.get("status") != "human_review_only"
        or tiers.get("pricesChanged") is not False
        or not isinstance(tiers.get("products"), list)
    ):
        raise ValueError("Unverified tier review report")

    if (
        not isinstance(technical, dict)
        or technical.get("schemaVersion") != 1
        or technical.get("status") != "technical_research_only"
        or technical.get("publishedPricesChanged") is not False
        or technical.get("flutterCalculationsChanged") is not False
        or not isinstance(technical.get("products"), list)
    ):
        raise ValueError("Unverified manufacturer review report")

    t_rows = [
        row for row in tiers["products"]
        if isinstance(row, dict) and row.get("id") in IDS
    ]
    c_rows = [
        row for row in technical["products"]
        if isinstance(row, dict) and row.get("id") in IDS
    ]

    if (
        len(t_rows) != len(IDS)
        or len(c_rows) != len(IDS)
        or {row["id"] for row in t_rows} != IDS
        or {row["id"] for row in c_rows} != IDS
    ):
        raise ValueError("Missing or duplicate six-product research evidence")

    technical_by_id = {row["id"]: row for row in c_rows}
    dossiers = []

    for tier_row in t_rows:
        product_id = tier_row["id"]
        maker = technical_by_id[product_id]
        key = tier_row.get("catalogMaterialKey")
        hint = tier_row.get("tierHintForHumanReview")

        if (
            key != maker.get("catalogMaterialKey")
            or hint != maker.get("tierHintForHumanReview")
            or key not in ("finishPutty", "interiorPaint")
            or hint not in ("budget", "standard", "premium")
        ):
            raise ValueError("Material identity or tier hint mismatch: " + product_id)

        if (
            tier_row.get("status") not in ("held", "manual_review_candidate")
            or tier_row.get("tierQualityReviewed") is not False
            or tier_row.get("approvedForPublication") is not False
            or maker.get("tierQualityApproved") is not False
            or maker.get("approvedForPublication") is not False
        ):
            raise ValueError("Research dossier cannot accept approved products")

        price = tier_row.get("candidateMedianMDL")
        if price is not None and (
            isinstance(price, bool)
            or not isinstance(price, (int, float))
            or not math.isfinite(price)
            or price <= 0
        ):
            raise ValueError("Invalid research price: " + product_id)

        technical_hold = (
            maker.get("requiresConsumptionReview") is True
            or maker.get("requiresRoomUseReview") is True
            or (
                key == "interiorPaint"
                and maker.get("roomCoverageCompatibleWithGenericTier") is not True
            )
        )

        flags = []
        if maker.get("requiresConsumptionReview") is True:
            flags.append("consumption_review")

        if (
            maker.get("requiresRoomUseReview") is True
            or (
                key == "interiorPaint"
                and maker.get("roomCoverageCompatibleWithGenericTier") is not True
            )
        ):
            flags.append("room_scope_incompatible")

        if tier_row.get("status") != "manual_review_candidate":
            flags.append("retail_evidence_missing")

        if tier_row.get("skuAndMethodReviewRequired") is True:
            flags.append("sku_and_method_review")

        if hint not in tier_row.get("exactPackMatchingTiers", []):
            if "retail_evidence_missing" not in flags:
                flags.append("retail_evidence_missing")

        flags.append("tier_quality_review")

        if technical_hold:
            priority = "P1"
            decision = "blocked_technical"
        elif (
            "retail_evidence_missing" in flags
            or "sku_and_method_review" in flags
        ):
            priority = "P2"
            decision = "manual_source_review_required"
        else:
            priority = "P3"
            decision = "manual_quality_review_required"

        dossiers.append({
            "id": product_id,
            "catalogMaterialKey": key,
            "tierHintOnly": hint,
            "priority": priority,
            "decision": decision,
            "researchPriceMedianMDL": price,
            "researchPriceIsNotApproved": True,
            "manufacturerUrl": maker.get("manufacturerUrl"),
            "manufacturerRoomUse": maker.get("manufacturerRoomUse"),
            "manufacturerKgPerM2": maker.get(
                "manufacturerKgPerM2ForConfiguredCoats"
            ),
            "appPreliminaryKgPerM2": maker.get("appPreliminaryKgPerM2"),
            "examplePackages": maker.get("examplePackages"),
            "shopObservations": tier_row.get("sourceObservations", []),
            "tierEvidenceStatus": tier_row.get("status"),
            "tierEvidenceReason": tier_row.get("reason"),
            "requiredManualChecks": flags,
            "approvedForPublication": False,
        })

    dossiers.sort(key=lambda row: (row["priority"], row["id"]))

    return {
        "schemaVersion": 1,
        "status": "research_only",
        "country": "MD",
        "currency": "MDL",
        "technicalEvidenceReviewDate": technical.get(
            "technicalEvidenceReviewDate"
        ),
        "summary": {
            "reviewed": len(dossiers),
            "priorityP1": sum(r["priority"] == "P1" for r in dossiers),
            "priorityP2": sum(r["priority"] == "P2" for r in dossiers),
            "priorityP3": sum(r["priority"] == "P3" for r in dossiers),
            "approvedForPublication": 0,
        },
        "products": dossiers,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
    }


def markdown(report):
    lines = [
        "# COSTARO — этап 27: досье шести материалов",
        "",
        "**Исследование. Ни одна цена не утверждена к публикации.**",
        "",
        "P1 — техническое несоответствие или неопределённый расход.",
        "P2 — требуется проверка магазинных данных и артикула.",
        "P3 — требуется оценка качества и назначения ценового уровня.",
        "",
        "| Приоритет | Материал | Подсказка уровня | Цена, MDL (исследование) | Решение |",
        "|---|---|---|---:|---|",
    ]

    for row in report["products"]:
        price = row["researchPriceMedianMDL"]
        shown = "—" if price is None else f"{price:.2f}"
        lines.append(
            f"| {row['priority']} | `{row['id']}` | "
            f"{row['tierHintOnly']} | {shown} | {row['decision']} |"
        )

    lines.extend(["", "## Что проверить вручную", ""])

    for row in report["products"]:
        lines.append(f"### {row['priority']} — `{row['id']}`")
        for flag in row["requiredManualChecks"]:
            lines.append(f"- {REASON_RU[flag]}")
        packs = row["examplePackages"] or {}
        if packs:
            lines.append(
                "- Пример на 50 м²: COSTARO — "
                f"{packs.get('appPreliminary')} уп.; "
                "по документации производителя — "
                f"{packs.get('manufacturerMinimum')}–"
                f"{packs.get('manufacturerMaximum')} уп."
            )
        lines.append(f"- Документация: {row['manufacturerUrl']}")
        lines.append("")

    lines.extend([
        "## Ограничения безопасности",
        "",
        "- Romanita нельзя утверждать как универсальную краску для влажных помещений.",
        "- Sansiro нельзя утверждать при текущей предварительной норме расхода.",
        "- Шпаклёвку с широким диапазоном расхода нужно проверить по технологии.",
        "- Цена не определяет качество и уровень «Бюджет / Стандарт / Премиум».",
        "- Все шесть товаров остаются исследовательскими кандидатами.",
        "- `prices.json`, нормы Flutter и действующие тарифы не изменены.",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tiers", type=Path, default=Path("material_tier_review.json")
    )
    parser.add_argument(
        "--technical",
        type=Path,
        default=Path("consumption_alignment_report.json"),
    )
    parser.add_argument(
        "--report", type=Path, default=Path("material_candidate_dossiers.json")
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("material_candidate_dossiers_RU.md"),
    )
    args = parser.parse_args()

    paths = [
        p.resolve()
        for p in (args.tiers, args.technical, args.report, args.markdown)
    ]
    if len(set(paths)) != len(paths):
        raise ValueError("Input and output report paths must differ")

    if args.report.exists() or args.markdown.exists():
        raise FileExistsError("Research dossier already exists")

    report = build(load(args.tiers), load(args.technical))
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    args.markdown.write_text(markdown(report), encoding="utf-8")

    print("=== COSTARO STAGE 27 MATERIAL DOSSIERS ===")
    print("Reviewed:", report["summary"]["reviewed"])
    print("P1:", report["summary"]["priorityP1"])
    print("P2:", report["summary"]["priorityP2"])
    print("P3:", report["summary"]["priorityP3"])
    print("Approved for publication: 0")
    print("Current prices and calculations were NOT changed.")


if __name__ == "__main__":
    main()