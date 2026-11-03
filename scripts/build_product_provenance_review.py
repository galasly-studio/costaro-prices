"""Guarded, research-only manufacturer and retailer provenance review."""

import json
import os
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit


SNAPSHOT_DATE = date(2026, 11, 3)

SOURCE_EVIDENCE = [
    {
        "catalogMaterialKey": "tileAdhesive",
        "researchProduct": "SUPRATEN NAS BAUND 25 kg",
        "manufacturerArticle": "510027",
        "manufacturerArticleSources": [
            "https://supraten.md/nas-baund-25kg-ro",
            (
                "https://supraten.md/i/Price_list/2019/"
                "PriceList-SUPRATEN-STANDART-01.03.2019.pdf"
            ),
        ],
        "retailerArticleCrossReference": {
            "seller": "PandaShop Moldova",
            "url": (
                "https://www.pandashop.md/ru/product/"
                "klej-plitochnyj-supraten-nas-baund-510027-00627468/"
            ),
            "manufacturerArticleShown": "510027",
            "retailerArticle": "00627468",
            "retailerClaimedEAN": "4841398000175",
            "manufacturerConfirmedEAN": False,
            "orderAvailabilityAtResearch": "not_orderable",
        },
        "temperatureClaimHistory": [
            {
                "claimC": 300,
                "sourceType": "historic_manufacturer_document",
                "sourceUrl": (
                    "https://supraten.md/i/brochures/"
                    "Fise_tehnice_rom.pdf"
                ),
            },
            {
                "claimC": 70,
                "sourceType": "current_manufacturer_product_page",
                "sourceUrl": "https://supraten.md/nas-baund-25kg-ro",
            },
            {
                "claimC": 250,
                "sourceType": "retailer_product_description",
                "sourceUrl": (
                    "https://avraamcec.md/products/"
                    "adeziv-nas-baund-25kg"
                ),
            },
        ],
        "manufacturerArticleCrossReferenced": True,
        "technicalConflictUnresolved": True,
        "remainingChecks": [
            "Confirm current manufacturer-issued EAN/GTIN",
            "Confirm code and barcode on a current retail package",
            "Resolve conflicting technical-document versions",
            "Verify current retail stock and identical product version",
            "Do not infer adhesive quality from retail price",
        ],
    },
    {
        "catalogMaterialKey": "cementPlaster",
        "researchProduct": "Baumit MPI 25 40 kg",
        "manufacturerPackageSource": (
            "https://baumit.ro/products/tencuieli-si-tinciuri/"
            "tencuieli-mecanizate/baumit-mpi-25"
        ),
        "manufacturerConfirmedPackageKg": 40,
        "crossBorderEANResearch": {
            "retailerClaimedEAN": "5945752000371",
            "manufacturerConfirmedEAN": False,
            "retailerSources": [
                (
                    "https://mugurel-bricolaj.ro/produs/"
                    "tencuiala-var-ciment-baumit-mpi-25-interior-"
                    "aplicare-manuala-sau-mecanizata-40-kg.html"
                ),
                "https://malinco.ro/p/mortar-mpi-25-baumit-40-kg/",
            ],
            "country": "RO",
            "moldovaRetailEANMapped": False,
        },
        "moldovaRetailSources": [
            (
                "https://stroimarket.md/"
                "tencuiala-var-ciment-baumit-mpi-25-40kg"
            ),
            (
                "https://avraamcec.md/products/"
                "tencuial-var-ciment-baumit-mpi-25-40kg"
            ),
        ],
        "manufacturerArticleCrossReferenced": False,
        "technicalConflictUnresolved": False,
        "remainingChecks": [
            "Obtain current manufacturer EAN/GTIN for 40 kg",
            "Confirm EAN on the Moldova retail package",
            "Check batch-specific technical documentation",
            "Confirm physical stock and package identity",
            "Do not use Romanian retail prices as Moldova prices",
        ],
    },
]


def build_report(crosscheck, queue, today=None):
    today = today or date.today()

    if crosscheck.get("status") != (
        "manual_retail_identity_crosscheck_only"
    ):
        raise ValueError("Unexpected Stage 36 report status.")

    previous = crosscheck.get("summary", {})

    if (
        previous.get("materialsWithPreliminaryNameAndPackMatch") != 2
        or previous.get("unresolvedSkuResearchTasks") != 8
    ):
        raise ValueError("Stage 36 baseline changed.")

    previous_materials = {
        item["catalogMaterialKey"]: item
        for item in crosscheck.get("materials", [])
    }

    expected = {"tileAdhesive", "cementPlaster"}

    if set(previous_materials) != expected:
        raise ValueError("Unexpected Stage 36 material identities.")

    if queue.get("summary", {}).get("totalManualResearchTasks") != 48:
        raise ValueError("Stage 35 manual queue changed.")

    reviewed = []

    for source in SOURCE_EVIDENCE:
        key = source["catalogMaterialKey"]

        if previous_materials[key].get("approvedForPublication") is not False:
            raise ValueError("Unexpected publication approval.")

        # Validate source URL shapes; do not fetch them or infer freshness.
        urls = []

        if key == "tileAdhesive":
            urls.extend(source["manufacturerArticleSources"])
            urls.append(source["retailerArticleCrossReference"]["url"])
            urls.extend(
                row["sourceUrl"]
                for row in source["temperatureClaimHistory"]
            )
        else:
            urls.append(source["manufacturerPackageSource"])
            urls.extend(
                source["crossBorderEANResearch"]["retailerSources"]
            )
            urls.extend(source["moldovaRetailSources"])

        for url in urls:
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.hostname:
                raise ValueError("Invalid provenance source URL.")

        reviewed.append({
            **source,
            "status": "documented_research_leads_not_approved",
            "sourceSnapshotDate": SNAPSHOT_DATE.isoformat(),
            "currentRetailAvailabilityVerified": False,
            "exactCurrentRetailPackageVerified": False,
            "independentTechnicalTestingVerified": False,
            "qualityTierApproved": False,
            "priceVerified": False,
            "approvedForPublication": False,
        })

    age = max(0, (today - SNAPSHOT_DATE).days)

    return {
        "schemaVersion": 1,
        "status": "manual_product_provenance_review_only",
        "sourceSnapshotDate": SNAPSHOT_DATE.isoformat(),
        "sourceSnapshotAgeDays": age,
        "sourceNeedsRefresh": age > 30,
        "sourcePagesFetchedDuringThisRun": False,
        "summary": {
            "materialsReviewed": 2,
            "manufacturerArticleCrossReferencesDocumented": 1,
            "crossBorderEANCandidatesForManualChecking": 1,
            "unresolvedTechnicalConflicts": 1,
            "unresolvedSkuTasks": 8,
            "closedSkuTasks": 0,
            "manufacturerConfirmedRetailEANs": 0,
            "currentRetailAvailabilityVerified": 0,
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "materials": reviewed,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "tierMappingsChanged": False,
        "automaticTierAssignmentEnabled": False,
        "automaticPublicationEnabled": False,
    }


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — происхождение технических сведений, этап 37",
        "",
        f"Дата исследования: {report['sourceSnapshotDate']}.",
        "",
        "Источники сохранены для ручной проверки. "
        "Этот запуск не скачивает и не подтверждает их заново.",
        "",
        f"Документальных сопоставлений артикула: "
        f"**{summary['manufacturerArticleCrossReferencesDocumented']}**.",
        "",
        f"Открытых задач проверки SKU: "
        f"**{summary['unresolvedSkuTasks']}**.",
        "",
        f"Закрытых задач: **{summary['closedSkuTasks']}**.",
        "",
        "Подтверждённых производителем EAN для продаваемых "
        "упаковок: **0**.",
        "",
        "## SUPRATEN NAȘ BAUND, 25 кг",
        "",
        "Артикул `510027` указан в историческом каталоге "
        "производителя и карточке PandaShop.",
        "",
        "Источники:",
        "",
    ]

    adhesive = next(
        item for item in report["materials"]
        if item["catalogMaterialKey"] == "tileAdhesive"
    )

    for url in adhesive["manufacturerArticleSources"]:
        lines.append(f"- {url}")

    lines.append(
        f"- {adhesive['retailerArticleCrossReference']['url']}"
    )

    lines.extend([
        "",
        "PandaShop указывает EAN `4841398000175`, "
        "но этот штрихкод не подтверждён производителем.",
        "",
        "Товар помечен продавцом как недоступный для заказа "
        "на дату исследования.",
        "",
        "### Противоречие температурных характеристик",
        "",
    ])

    for item in adhesive["temperatureClaimHistory"]:
        lines.append(
            f"- {item['sourceType']}: "
            f"+{item['claimC']} °C — {item['sourceUrl']}"
        )

    lines.extend([
        "",
        "**Вывод:** нельзя переносить ни одно из этих значений "
        "в классификацию качества без подтверждения "
        "актуальной версии материала.",
        "",
        "## Baumit MPI 25, 40 кг",
        "",
    ])

    cement = next(
        item for item in report["materials"]
        if item["catalogMaterialKey"] == "cementPlaster"
    )

    lines.extend([
        "Производитель подтверждает выпуск упаковки 40 кг:",
        "",
        cement["manufacturerPackageSource"],
        "",
        "Два продавца Румынии указывают одинаковый EAN "
        "`5945752000371`:",
        "",
    ])

    for url in cement["crossBorderEANResearch"]["retailerSources"]:
        lines.append(f"- {url}")

    lines.extend([
        "",
        "Карточки магазинов Молдовы:",
        "",
    ])

    for url in cement["moldovaRetailSources"]:
        lines.append(f"- {url}")

    lines.extend([
        "",
        "**Вывод:** EAN остаётся кандидатом для проверки. "
        "Совпадение с фактически продаваемой в Молдове "
        "упаковкой не подтверждено.",
        "",
        "## Ограничения безопасности",
        "",
        "- Ни одна задача проверки SKU автоматически не закрыта.",
        "- Наличие товара не подтверждено этим запуском.",
        "- Исторические документы не заменяют актуальный техпаспорт.",
        "- Сведения продавца не считаются независимым испытанием.",
        "- Категории качества не присваиваются.",
        "- Действующие цены, нормы и формулы не изменяются.",
        "- Автоматическая публикация отключена.",
        "",
    ])

    if report["sourceNeedsRefresh"]:
        lines.append(
            "**ВНИМАНИЕ:** источникам более 30 дней; "
            "их необходимо повторно проверить."
        )

    return "\n".join(lines) + "\n"


def main():
    crosscheck = json.loads(
        Path("retail_identity_crosscheck.json").read_text(
            encoding="utf-8"
        )
    )

    queue = json.loads(
        Path("manufacturer_review_queue.json").read_text(
            encoding="utf-8"
        )
    )

    report = build_report(crosscheck, queue)
    markdown = render_markdown(report)

    Path("product_provenance_review.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    Path("product_provenance_review_RU.md").write_text(
        markdown,
        encoding="utf-8",
    )

    print(
        "COSTARO Stage 37: "
        "1 documented manufacturer article cross-reference; "
        "1 EAN candidate; "
        "1 unresolved technical conflict; "
        "0 approved SKU mappings."
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_path:
        with Path(summary_path).open(
            "a", encoding="utf-8"
        ) as output:
            output.write(markdown)


if __name__ == "__main__":
    main()
