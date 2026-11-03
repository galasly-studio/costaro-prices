"""Research-only comparison of manufacturer and Moldova retail identities."""

import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit


SNAPSHOT_DATE = date(2026, 11, 3)

EXPECTED_KEYS = {
    "cementPlaster",
    "electricalLightingCablePerM",
    "electricalSocketCablePerM",
    "gypsumPlaster",
    "laminatePerM2",
    "primer",
    "tileAdhesive",
    "tilePerM2",
}

RESEARCH_LEADS = [
    {
        "catalogMaterialKey": "cementPlaster",
        "researchProduct": "Baumit MPI 25",
        "packageKg": 40,
        "manufacturerSourceUrl": (
            "https://baumit.ro/files/ro/pdf_files/"
            "pds_mpi__5_bro_ro_13681.pdf"
        ),
        "retailerPages": [
            {
                "seller": "StroiMarket",
                "url": (
                    "https://stroimarket.md/"
                    "tencuiala-var-ciment-baumit-mpi-25-40kg"
                ),
                "retailerArticle": "659",
                "manufacturerOwnedStore": False,
            },
            {
                "seller": "AVRAAMCEC VIO",
                "url": (
                    "https://avraamcec.md/products/"
                    "tencuial-var-ciment-baumit-mpi-25-40kg"
                ),
                "retailerArticle": None,
                "manufacturerOwnedStore": False,
            },
        ],
        "technicalDiscrepancies": [],
        "manualChecksRequired": [
            "Manufacturer EAN/GTIN and exact retail product identity",
            "Current physical stock and package photograph",
            "Current technical document for the sold batch",
            "Suitability for the exact COSTARO application",
        ],
    },
    {
        "catalogMaterialKey": "tileAdhesive",
        "researchProduct": "SUPRATEN NAS BAUND",
        "packageKg": 25,
        "manufacturerSourceUrl": (
            "https://supraten.md/nas-baund-25kg-ro"
        ),
        "retailerPages": [
            {
                "seller": "SUPRATEN official store",
                "url": "https://supraten.md/nas-baund-25kg-ro",
                "retailerArticle": "510027",
                "manufacturerOwnedStore": True,
            },
            {
                "seller": "AVRAAMCEC VIO",
                "url": (
                    "https://avraamcec.md/products/"
                    "adeziv-nas-baund-25kg"
                ),
                "retailerArticle": None,
                "manufacturerOwnedStore": False,
            },
        ],
        "technicalDiscrepancies": [
            {
                "topic": "Temperature resistance",
                "manufacturerPageStatementC": 70,
                "retailerPageStatementC": 250,
                "status": "unresolved_conflicting_claims",
                "manualAction": (
                    "Confirm product version, current technical "
                    "datasheet, and applicability of both claims."
                ),
            }
        ],
        "manualChecksRequired": [
            "Manufacturer article to independent retailer SKU mapping",
            "Resolve contradictory temperature statements",
            "Current physical stock and package photograph",
            "Full technical classification and intended application",
        ],
    },
]


def build_report(manufacturer_leads, review_queue, today=None):
    """Build a strictly non-approving research report."""
    today = today or date.today()

    if manufacturer_leads.get("status") is None:
        raise ValueError("Manufacturer research report is missing status.")

    candidates = manufacturer_leads.get("candidates", [])
    by_key = {
        item["catalogMaterialKey"]: item
        for item in candidates
    }

    if len(candidates) != 8 or set(by_key) != EXPECTED_KEYS:
        raise ValueError("Unexpected manufacturer candidate coverage.")

    summary = review_queue.get("summary", {})

    if summary.get("totalManualResearchTasks") != 48:
        raise ValueError("Stage 35 research queue has changed.")

    sku_tasks = [
        task for task in review_queue.get("tasks", [])
        if task.get("taskType") == "verify_exact_moldova_sku"
    ]

    if (
        len(sku_tasks) != 8
        or {t["catalogMaterialKey"] for t in sku_tasks} != EXPECTED_KEYS
    ):
        raise ValueError("Expected eight unresolved SKU research tasks.")

    records = []

    for lead in RESEARCH_LEADS:
        key = lead["catalogMaterialKey"]

        if (
            by_key[key].get("sourceUrl")
            != lead["manufacturerSourceUrl"]
        ):
            raise ValueError(
                f"Manufacturer source mismatch for {key}."
            )

        retailer_domains = set()

        for listing in lead["retailerPages"]:
            parsed = urlsplit(listing["url"])

            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("Invalid retailer evidence URL.")

            retailer_domains.add(parsed.hostname.lower())

        if len(retailer_domains) < 2:
            raise ValueError("Two distinct retail domains required.")

        records.append({
            **lead,
            "researchStatus": "preliminary_name_and_pack_match_only",
            "sourceSnapshotDate": SNAPSHOT_DATE.isoformat(),
            "manufacturerToRetailSkuVerified": False,
            "currentStockIndependentlyVerified": False,
            "technicalClaimsIndependentlyVerified": False,
            "qualityTierApproved": False,
            "approvedForPublication": False,
            "priceDateVerified": False,
        })

    age_days = max(0, (today - SNAPSHOT_DATE).days)

    report = {
        "schemaVersion": 1,
        "status": "manual_retail_identity_crosscheck_only",
        "sourceSnapshotDate": SNAPSHOT_DATE.isoformat(),
        "snapshotAgeDays": age_days,
        "snapshotNeedsRefresh": age_days > 30,
        "sourcePagesFetchedDuringThisRun": False,
        "summary": {
            "priorityMaterials": 8,
            "materialsWithPreliminaryNameAndPackMatch": 2,
            "retailerPageLeads": 4,
            "technicalDiscrepancyFlags": 1,
            "unresolvedSkuResearchTasks": 8,
            "manufacturerRetailSkuCrosswalksVerified": 0,
            "independentlyVerifiedTechnicalClaims": 0,
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "materials": records,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "tierMappingsChanged": False,
        "automaticTierAssignmentEnabled": False,
        "automaticPublicationEnabled": False,
    }

    return report


def render_markdown(report):
    s = report["summary"]

    lines = [
        "# COSTARO — предварительная сверка товаров, этап 36",
        "",
        f"Дата исходного исследования: {report['sourceSnapshotDate']}.",
        "",
        "Исходные ссылки сохранены для ручной проверки. "
        "Этот запуск не загружает сайты повторно.",
        "",
        f"Предварительных совпадений названия и упаковки: "
        f"**{s['materialsWithPreliminaryNameAndPackMatch']}**.",
        "",
        f"Карточек продавцов: **{s['retailerPageLeads']}**.",
        "",
        f"Противоречий в характеристиках: "
        f"**{s['technicalDiscrepancyFlags']}**.",
        "",
        f"Открытых задач проверки SKU: "
        f"**{s['unresolvedSkuResearchTasks']}**.",
        "",
        "Подтверждённых соответствий артикула производителя "
        "и артикула продавца: **0**.",
        "",
        "Утверждённых категорий качества: **0**.",
        "",
        "## Найденные товары",
        "",
    ]

    for material in report["materials"]:
        lines.extend([
            f"### {material['researchProduct']}, "
            f"{material['packageKg']} кг",
            "",
            f"Ключ каталога: `{material['catalogMaterialKey']}`.",
            "",
            "Документ производителя:",
            material["manufacturerSourceUrl"],
            "",
            "Карточки продавцов:",
            "",
        ])

        for page in material["retailerPages"]:
            article = page["retailerArticle"] or "не установлен"

            lines.append(
                f"- {page['seller']}: {page['url']} "
                f"(код магазина: {article})"
            )

        lines.extend([
            "",
            "Остаётся проверить:",
            "",
        ])

        for task in material["manualChecksRequired"]:
            lines.append(f"- {task}")

        for conflict in material["technicalDiscrepancies"]:
            lines.extend([
                "",
                "**Техническое противоречие:**",
                (
                    f"Производитель: "
                    f"+{conflict['manufacturerPageStatementC']} °C; "
                    f"продавец: "
                    f"+{conflict['retailerPageStatementC']} °C."
                ),
                "",
                "Характеристика НЕ подтверждена.",
            ])

        lines.append("")

    lines.extend([
        "## Защитные ограничения",
        "",
        "- Сведения являются исследовательскими, не одобренными.",
        "- Предварительное совпадение не закрывает задачу проверки SKU.",
        "- Наличие товара и цена не проверены в текущем запуске.",
        "- Информация продавца не считается независимым испытанием.",
        "- Категории Бюджет/Стандарт/Премиум не присваиваются.",
        "- Цены, нормы, формулы и действующий каталог не изменены.",
        "- Автоматическая публикация отключена.",
        "",
    ])

    if report["snapshotNeedsRefresh"]:
        lines.extend([
            "**ВНИМАНИЕ:** исследовательские ссылки старше 30 дней. "
            "Необходима повторная проверка.",
            "",
        ])

    return "\n".join(lines)


def main():
    leads = json.loads(
        Path("manufacturer_evidence_leads.json").read_text(
            encoding="utf-8"
        )
    )
    queue = json.loads(
        Path("manufacturer_review_queue.json").read_text(
            encoding="utf-8"
        )
    )

    report = build_report(leads, queue)
    markdown = render_markdown(report)

    Path("retail_identity_crosscheck.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    Path("retail_identity_crosscheck_RU.md").write_text(
        markdown,
        encoding="utf-8",
    )

    print(
        "COSTARO Stage 36: "
        "2 preliminary product matches, "
        "1 technical discrepancy, "
        "0 verified SKUs, "
        "0 approvals."
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_path:
        with Path(summary_path).open(
            "a", encoding="utf-8"
        ) as output:
            output.write(markdown + "\n")


if __name__ == "__main__":
    main()
