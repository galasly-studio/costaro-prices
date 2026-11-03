#!/usr/bin/env python3
"""Research-only comparison of three documented material candidates.

Manufacturer descriptions establish technical properties, not independently
verified budget/standard/premium quality rankings. Never update prices or policy.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
from pathlib import Path

from validate_app_catalog import load


REVIEW_DATE = date(2026, 11, 3)
MAX_EVIDENCE_AGE_DAYS = 90

PRODUCTS = {
    "glet_b62_satroc_8kg": {
        "label": "Шпаклёвка B-62 SATROC, 8 кг",
        "materialKey": "finishPutty",
        "tierHint": "standard",
        "packageKg": 8,
        "manufacturerUrl":
            "https://supraten.md/glet-b-62-satroc-8kg-54796-ro",
        "verifiedClaims": [
            "Финишная акриловая шпаклёвка для внутренних работ",
            "Производитель указывает более мелкую фракцию",
            "Предусмотрено ручное нанесение",
            "После высыхания поверхность можно шлифовать",
        ],
        "missingQualityEvidence": [
            "Независимое сравнение характеристик с другими шпаклёвками",
            "Подтверждение объективных критериев стандартного уровня",
        ],
    },
    "glet_satroc_8kg": {
        "label": "Шпаклёвка SATROC, 8 кг",
        "materialKey": "finishPutty",
        "tierHint": "premium",
        "packageKg": 8,
        "manufacturerUrl":
            "https://supraten.md/shpatlevka-satroc-8kg-54810-ru",
        "verifiedClaims": [
            "Финишная акриловая шпаклёвка для внутренних работ",
            "Производитель описывает ручное нанесение",
            "Производитель описывает механизированное нанесение",
            "Заявлено отсутствие растворителей и запаха",
            "После высыхания поверхность можно шлифовать",
        ],
        "missingQualityEvidence": [
            "Независимое подтверждение преимуществ перед B-62",
            "Достаточные критерии для присвоения премиального уровня",
        ],
    },
    "euroton_lav_7kg": {
        "label": "Краска EUROTON LAV, 7 кг",
        "materialKey": "interiorPaint",
        "tierHint": "standard",
        "packageKg": 7,
        "manufacturerUrl":
            "https://supraten.md/vopsea-euroton-lav-7kg-55106-ro",
        "verifiedClaims": [
            "Интерьерная акриловая краска",
            "Предназначена для сухих и влажных помещений",
            "Производитель заявляет устойчивость к мытью и трению",
            "Рекомендуется нанесение в два слоя",
            "Заявлена паропроницаемость покрытия",
        ],
        "missingQualityEvidence": [
            "Объективный класс стойкости к мокрому истиранию",
            "Сравнительные данные для стандартного ценового уровня",
        ],
    },
}


def _by_id(rows):
    if not isinstance(rows, list):
        raise ValueError("Product rows are missing")
    result = {}
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            raise ValueError("Invalid research product")
        if row["id"] in result:
            raise ValueError("Duplicate product ID")
        result[row["id"]] = row
    return result


def build(tier_report, technical_report, *, now=None):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    age = (now.date() - REVIEW_DATE).days

    if age < 0:
        raise ValueError("Manufacturer review date is in the future")

    if (
        tier_report.get("schemaVersion") != 1
        or tier_report.get("status") != "human_review_only"
        or tier_report.get("pricesChanged") is not False
    ):
        raise ValueError("Invalid research-only tier report")

    if (
        technical_report.get("schemaVersion") != 1
        or technical_report.get("status") != "technical_research_only"
        or technical_report.get("publishedPricesChanged") is not False
        or technical_report.get("flutterCalculationsChanged") is not False
    ):
        raise ValueError("Invalid technical evidence")

    tiers = _by_id(tier_report.get("products"))
    technical = _by_id(technical_report.get("products"))
    rows = []

    for product_id, expected in PRODUCTS.items():
        source = tiers.get(product_id)
        maker = technical.get(product_id)

        if not source or not maker:
            raise ValueError("Missing manufacturer research: " + product_id)

        if (
            source.get("catalogMaterialKey") != expected["materialKey"]
            or maker.get("catalogMaterialKey") != expected["materialKey"]
            or source.get("tierHintForHumanReview") != expected["tierHint"]
            or maker.get("tierHintForHumanReview") != expected["tierHint"]
            or maker.get("packageWeightKg") != expected["packageKg"]
            or maker.get("manufacturerUrl") != expected["manufacturerUrl"]
        ):
            raise ValueError("Product identity or package mismatch: " + product_id)

        if (
            source.get("tierQualityReviewed") is not False
            or source.get("approvedForPublication") is not False
            or maker.get("tierQualityApproved") is not False
            or maker.get("approvedForPublication") is not False
            or source.get("status") not in (
                "held", "manual_review_candidate"
            )
        ):
            raise ValueError("Unexpected quality or publication approval")

        norm_compatible = maker.get("requiresConsumptionReview") is False
        room_compatible = (
            maker.get("roomCoverageCompatibleWithGenericTier") is True
            if expected["materialKey"] == "interiorPaint"
            else None
        )

        technical_match = (
            norm_compatible
            and room_compatible is not False
            and expected["tierHint"] in source.get(
                "exactPackMatchingTiers", []
            )
        )

        rows.append({
            "id": product_id,
            "label": expected["label"],
            "catalogMaterialKey": expected["materialKey"],
            "tierHintForHumanReview": expected["tierHint"],
            "qualityTierVerified": False,
            "approvedForPublication": False,
            "researchPriceMedianMDL":
                source.get("candidateMedianMDL"),
            "shopEvidence":
                source.get("sourceObservations", []),
            "sourceResearchStatus": source.get("status"),
            "manufacturerUrl": expected["manufacturerUrl"],
            "manufacturerClaims": expected["verifiedClaims"],
            "missingIndependentQualityEvidence":
                expected["missingQualityEvidence"],
            "consumptionPreliminarilyCompatible": norm_compatible,
            "roomCoverageCompatibleWithGenericTier": room_compatible,
            "technicalPreliminaryMatch": technical_match,
            "manufacturerConsumptionKgPerM2":
                maker.get("manufacturerKgPerM2ForConfiguredCoats"),
            "appPreliminaryKgPerM2":
                maker.get("appPreliminaryKgPerM2"),
            "manufacturerEvidenceFresh":
                age <= MAX_EVIDENCE_AGE_DAYS,
        })

    return {
        "schemaVersion": 1,
        "status": "manufacturer_quality_research_only",
        "generatedAt": now.isoformat(),
        "manufacturerReviewDate": REVIEW_DATE.isoformat(),
        "manufacturerEvidenceAgeDays": age,
        "manufacturerEvidenceFresh": age <= MAX_EVIDENCE_AGE_DAYS,
        "summary": {
            "productsReviewed": len(rows),
            "technicalPreliminaryMatches": sum(
                row["technicalPreliminaryMatch"] for row in rows
            ),
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "products": rows,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
    }


def markdown(report):
    lines = [
        "# COSTARO — этап 29: качество материалов",
        "",
        "**Только исследование. Цены и формулы не менялись.**",
        "",
        "Документация производителя подтверждает отдельные свойства товара,",
        "но сама по себе не устанавливает объективный уровень качества.",
        "",
        f"Дата проверки источников: {report['manufacturerReviewDate']}",
        f"Возраст исследования: {report['manufacturerEvidenceAgeDays']} дней.",
        "",
        "| Материал | Уровень — подсказка | Техническая совместимость | Качество утверждено |",
        "|---|---|---|---|",
    ]

    for row in report["products"]:
        match = "предварительно да" if row["technicalPreliminaryMatch"] else "требует проверки"
        lines.append(
            f"| {row['label']} | {row['tierHintForHumanReview']} "
            f"| {match} | нет |"
        )

    for row in report["products"]:
        lines.extend([
            "",
            f"## {row['label']}",
            "",
            "### Что указано производителем",
        ])
        for claim in row["manufacturerClaims"]:
            lines.append("- " + claim)

        lines.extend(["", "### Что ещё нужно подтвердить"])
        for item in row["missingIndependentQualityEvidence"]:
            lines.append("- " + item)

        lines.extend([
            "",
            f"Официальный источник: {row['manufacturerUrl']}",
            "",
            "**Присвоение уровня не утверждено.**",
        ])

    lines.extend([
        "",
        "## Ограничения",
        "",
        "- Уровни budget/standard/premium не присваиваются автоматически.",
        "- Описание производителя не заменяет независимое сравнение качества.",
        "- Данные старше 90 дней требуют повторной проверки.",
        "- Нормы и формулы COSTARO остаются неизменными.",
        "- Действующий каталог цен не изменён.",
        "",
    ])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tiers",
        type=Path,
        default=Path("material_tier_review.json"),
    )
    parser.add_argument(
        "--technical",
        type=Path,
        default=Path("consumption_alignment_report.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("material_quality_dossiers.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("material_quality_dossiers_RU.md"),
    )
    args = parser.parse_args()

    paths = [
        path.resolve()
        for path in (
            args.tiers, args.technical, args.report, args.markdown
        )
    ]
    if len(set(paths)) != len(paths):
        raise ValueError("Input and output paths must differ")
    if args.report.exists() or args.markdown.exists():
        raise FileExistsError("Quality report already exists")

    report = build(load(args.tiers), load(args.technical))
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

    print("=== COSTARO STAGE 29 QUALITY RESEARCH ===")
    print("Products:", report["summary"]["productsReviewed"])
    print(
        "Preliminary technical matches:",
        report["summary"]["technicalPreliminaryMatches"],
    )
    print("Approved quality tiers: 0")
    print("Published prices and Flutter formulas NOT changed.")


if __name__ == "__main__":
    main()