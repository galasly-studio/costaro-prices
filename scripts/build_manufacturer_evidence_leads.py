"""COSTARO Stage 34: manufacturer technical source leads.

The source links and attributed manufacturer statements are research leads.
They do not establish independent quality verification, market availability,
quality tiers, prices, or permission to publish catalog changes.
"""

from datetime import date, datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlsplit


RESEARCH_DATE = date(2026, 11, 3)
MAX_RESEARCH_AGE_DAYS = 90


LEADS = {
    "tileAdhesive": {
        "nameRu": "SUPRATEN NAȘ BAUND, 25 кг",
        "scope": "exact_model",
        "url": "https://supraten.md/nas-baund-25kg-ro",
        "claims": [
            (
                "adhesiveType",
                "Производитель описывает клей как цементный, армированный волокнами.",
            ),
            (
                "openTime",
                "Заявлено увеличенное открытое время; подтверждённый класс ещё требуется проверить.",
            ),
            (
                "substrateCompatibility",
                "Заявлено применение для керамической облицовки внутри и снаружи.",
            ),
        ],
    },

    "primer": {
        "nameRu": "Knauf Betokontakt",
        "scope": "exact_model",
        "url": (
            "https://knauf.com/api/download-center/v1/assets/"
            "27a0a66b-9109-4568-8c0e-b23f8a8c2c22"
            "?country=ro&download=true"
        ),
        "claims": [
            (
                "primerType",
                "Контактная грунтовка с кварцевым наполнителем для гладких оснований.",
            ),
            (
                "substrates",
                "Предназначена, в частности, для плотных бетонных оснований.",
            ),
            (
                "consumption",
                "В техлисте указан ориентир около 225 г/м²; на некоторых основаниях до 350 г/м².",
            ),
        ],
    },

    "gypsumPlaster": {
        "nameRu": "Knauf MP 75",
        "scope": "exact_model",
        "url": (
            "https://knauf.com/api/download-center/v1/assets/"
            "31f2aba7-6983-41e3-8b04-79317afee722"
            "?country=ro&download=true"
        ),
        "claims": [
            (
                "roomUse",
                "Гипсовая штукатурка для внутренних помещений с указанными производителем условиями влажности.",
            ),
            (
                "layerThickness",
                "Для стен заявлена толщина нанесения 8–30 мм.",
            ),
            (
                "consumption",
                "Ориентировочный расход 10 кг/м² при толщине 10 мм.",
            ),
            (
                "strength",
                "Заявлена прочность на сжатие более 3,5 Н/мм².",
            ),
        ],
    },

    "cementPlaster": {
        "nameRu": "Baumit MPI 25",
        "scope": "product_line",
        "url": "https://baumit.ro/files/ro/pdf_files/pds_mpi__5_bro_ro_13681.pdf",
        "claims": [
            (
                "roomUse",
                "Известково-цементная штукатурка для внутренних помещений, включая указанные влажные помещения.",
            ),
            (
                "layerThickness",
                "В техлисте указан диапазон толщины 10–25 мм для обычного нанесения.",
            ),
            (
                "consumption",
                "Заявлен расход около 14 кг/м² на 1 см толщины.",
            ),
            (
                "strength",
                "Заявлена прочность на сжатие через 28 суток более 2,5 Н/мм².",
            ),
        ],
    },

    "tilePerM2": {
        "nameRu": "Ispan-Lux — керамогранит, декларация типа продукции",
        "scope": "product_type",
        "url": (
            "https://storage.mtender.gov.md/get/"
            "d026a57a-92eb-402d-8239-d44bfd3c8bc5-1772227507813"
        ),
        "claims": [
            (
                "tileClassification",
                "В декларации описан тип сухопрессованной керамической плитки.",
            ),
            (
                "waterAbsorption",
                "Для указанного типа керамогранита декларировано водопоглощение не более 0,5%.",
            ),
        ],
    },

    "laminatePerM2": {
        "nameRu": "EGGER Laminate Flooring Aqua+",
        "scope": "product_line",
        "url": (
            "https://www.egger.com/get_download/"
            "24a0e252-ece9-4a65-ada9-05663f7a6083/"
            "TDS_EGGER_Laminate_Flooring_aqua_en.pdf"
        ),
        "claims": [
            (
                "useClass",
                "В техническом листе серии указан класс применения 32.",
            ),
        ],
    },

    "electricalLightingCablePerM": {
        "nameRu": "Nexans NYM-J 3G1,5 — технический пример",
        "scope": "exact_model",
        "url": (
            "https://latrivenetacavi.nexans.com/en/products/"
            "residential-and-commercial/residential-commercial-Eca-class/"
            "NYM-J38596/product~090121044~.html"
        ),
        "claims": [
            (
                "conductorSection",
                "В карточке изделия указано номинальное сечение 1,5 мм².",
            ),
            (
                "conductorMaterial",
                "Указаны три медные жилы, включая защитную.",
            ),
            (
                "ratedVoltage",
                "Заявлено номинальное напряжение 300/500 В.",
            ),
        ],
    },

    "electricalSocketCablePerM": {
        "nameRu": "Nexans NYM-J 3G2,5 — технический пример",
        "scope": "exact_model",
        "url": (
            "https://latrivenetacavi.nexans.com/en/products/"
            "residential-and-commercial/residential-commercial-Eca-class/"
            "NYM-J38596/product~090123044~.html"
        ),
        "claims": [
            (
                "conductorSection",
                "В карточке изделия указано номинальное сечение 2,5 мм².",
            ),
            (
                "conductorMaterial",
                "Указаны три медные жилы, включая защитную.",
            ),
            (
                "ratedVoltage",
                "Заявлено номинальное напряжение 300/500 В.",
            ),
        ],
    },
}


ALLOWED_HOSTS = {
    "supraten.md",
    "knauf.com",
    "baumit.ro",
    "storage.mtender.gov.md",
    "www.egger.com",
    "latrivenetacavi.nexans.com",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build(priority_report, leads=None, *, today=None):
    research = LEADS if leads is None else leads
    today = today or datetime.now(timezone.utc).date()

    require(
        isinstance(today, date),
        "Invalid review date",
    )

    age_days = (today - RESEARCH_DATE).days

    require(
        age_days >= 0,
        "Research date is in the future",
    )

    require(
        priority_report.get("schemaVersion") == 1
        and priority_report.get("policyVersion") == 1
        and priority_report.get("status")
            == "priority_quality_evidence_requirements_only",
        "Unexpected Stage 33 report",
    )

    for flag in (
        "publishedPricesChanged",
        "flutterCalculationsChanged",
        "tierMappingsChanged",
        "automaticTierAssignmentEnabled",
        "automaticPublicationEnabled",
    ):
        require(
            priority_report.get(flag) is False,
            "Unsafe source flag: " + flag,
        )

    summary = priority_report.get("summary", {})

    require(
        summary.get("catalogMaterials") == 41
        and summary.get("newPriorityProfiles") == 8
        and summary.get("totalMaterialsWithIndividualCriteria") == 10
        and summary.get("materialsStillAwaitingIndividualCriteria") == 31
        and summary.get("technicalEvidenceRequirements") == 40
        and summary.get("verifiedEvidenceRequirements") == 0
        and summary.get("qualityTiersApproved") == 0
        and summary.get("approvedForPublication") == 0,
        "Unexpected Stage 33 evidence or publication state",
    )

    rows = priority_report.get("materials")

    require(
        isinstance(rows, list) and len(rows) == 8,
        "Expected eight priority criteria profiles",
    )

    profiles = {}

    for row in rows:
        require(
            isinstance(row, dict),
            "Invalid priority material",
        )

        key = row.get("catalogMaterialKey")

        require(
            isinstance(key, str) and key not in profiles,
            "Duplicate priority material",
        )

        require(
            row.get("qualityTier") == "unclassified"
            and row.get("qualityTierApproved") is False
            and row.get("approvedForPublication") is False,
            "Unexpected quality approval",
        )

        criteria = row.get("technicalChecks")

        require(
            isinstance(criteria, list) and len(criteria) >= 5,
            "Missing technical criteria",
        )

        criterion_ids = set()

        for item in criteria:
            require(
                isinstance(item, dict),
                "Invalid criterion",
            )

            criterion_id = item.get("criterionId")

            require(
                isinstance(criterion_id, str)
                and criterion_id not in criterion_ids,
                "Duplicate criterion ID",
            )

            require(
                item.get("verifiedValue") is None
                and item.get("evidenceProvided") is False
                and item.get("evidenceReviewed") is False,
                "Unexpected verified evidence in source",
            )

            criterion_ids.add(criterion_id)

        profiles[key] = criterion_ids

    require(
        isinstance(research, dict)
        and len(research) == 8
        and set(research) == set(profiles),
        "Manufacturer source coverage differs from priority materials",
    )

    stale = age_days > MAX_RESEARCH_AGE_DAYS

    result = []
    total_claims = 0

    for key, lead in research.items():
        url = lead.get("url")

        require(
            isinstance(url, str),
            "Missing manufacturer URL",
        )

        parsed = urlsplit(url)

        require(
            parsed.scheme == "https"
            and parsed.hostname in ALLOWED_HOSTS,
            "Unexpected source host for " + key,
        )

        require(
            lead.get("scope") in (
                "exact_model",
                "product_line",
                "product_type",
            ),
            "Invalid source specificity",
        )

        statements = lead.get("claims")

        require(
            isinstance(statements, (list, tuple))
            and len(statements) > 0,
            "No attributed manufacturer statements",
        )

        seen = set()
        claims = []

        for statement in statements:
            require(
                isinstance(statement, (tuple, list))
                and len(statement) == 2,
                "Invalid manufacturer statement",
            )

            criterion_id, declared_value = statement

            require(
                criterion_id in profiles[key]
                and criterion_id not in seen
                and isinstance(declared_value, str)
                and bool(declared_value.strip()),
                "Unknown or duplicate manufacturer statement",
            )

            seen.add(criterion_id)

            claims.append({
                "criterionId": criterion_id,
                "manufacturerStatementRu": declared_value,
                "independentlyVerified": False,
                "approvedAsQualityEvidence": False,
            })

        total_claims += len(claims)

        result.append({
            "catalogMaterialKey": key,
            "researchProductRu": lead["nameRu"],
            "sourceUrl": url,
            "sourceSpecificity": lead["scope"],
            "sourceReviewedOn": RESEARCH_DATE.isoformat(),
            "sourceUrlCheckedByWorkflow": False,
            "sourceNeedsManualRefresh": stale,
            "exactRetailSkuInMoldovaVerified": False,
            "sourceClaims": claims,
            "missingIndividualEvidenceCount": (
                len(profiles[key]) - len(claims)
            ),
            "independentQualityComparisonVerified": False,
            "suitabilityForEveryCostaroRoomVerified": False,
            "qualityTierApproved": False,
            "approvedForPublication": False,
        })

    result.sort(key=lambda row: row["catalogMaterialKey"])

    return {
        "schemaVersion": 1,
        "status": "manufacturer_source_leads_research_only",
        "sourceReviewDate": RESEARCH_DATE.isoformat(),
        "sourceResearchAgeDays": age_days,
        "summary": {
            "priorityMaterials": 8,
            "candidateTechnicalSources": len(result),
            "manufacturerStatementsRecorded": total_claims,
            "sourcesNeedingManualRefresh": (
                len(result) if stale else 0
            ),
            "independentlyVerifiedClaims": 0,
            "verifiedMoldovaRetailSkuMappings": 0,
            "materialsWithCompleteApprovedEvidence": 0,
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "candidates": result,
        "manufacturerStatementsAreNotIndependentTests": True,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
        "automaticTierAssignmentEnabled": False,
        "automaticPublicationEnabled": False,
    }


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — этап 34: технические документы производителей",
        "",
        "**Исследовательские источники. Не подтверждение качества или цены.**",
        "",
        f"- Материалов: **{summary['priorityMaterials']}**",
        f"- Источников-кандидатов: **{summary['candidateTechnicalSources']}**",
        (
            "- Записанных заявлений производителей: "
            f"**{summary['manufacturerStatementsRecorded']}**"
        ),
        "- Независимо проверенных характеристик: **0**",
        "- Подтверждённых артикулов в продаже в Молдове: **0**",
        "- Утверждённых категорий качества: **0**",
        "- Разрешений на публикацию: **0**",
        "",
    ]

    for item in report["candidates"]:
        lines.extend([
            f"## {item['researchProductRu']}",
            "",
            f"Каталог COSTARO: `{item['catalogMaterialKey']}`",
            "",
            f"Источник: {item['sourceUrl']}",
            "",
            f"Уровень точности документа: `{item['sourceSpecificity']}`",
            "",
            "### Заявленные производителем сведения",
            "",
        ])

        for claim in item["sourceClaims"]:
            lines.append(
                "- **" + claim["criterionId"] + ":** "
                + claim["manufacturerStatementRu"]
            )

        lines.extend([
            "",
            "Требуется ручная проверка документа, применимости, "
            "точного артикула и сопоставимости характеристик.",
            "",
        ])

    lines.extend([
        "## Ограничения",
        "",
        "- Ссылки не проверяются автоматически при каждом запуске.",
        "- Некоторые источники относятся к серии или типу товара.",
        "- Доступность конкретных артикулов в Молдове не установлена.",
        "- Кабели — технические примеры, а не рекомендации по проектированию сети.",
        "- Заявления производителя ещё не являются независимыми испытаниями.",
        "- По цене качество не определяется.",
        "- Действующие цены, нормы расхода и формулы COSTARO сохранены.",
        "",
    ])

    return "\n".join(lines)


def main():
    priority_report = json.loads(
        Path("priority_material_criteria.json").read_text(
            encoding="utf-8"
        )
    )

    output_json = Path("manufacturer_evidence_leads.json")
    output_md = Path("manufacturer_evidence_leads_RU.md")

    if output_json.exists() or output_md.exists():
        raise FileExistsError("Stage 34 report already exists")

    report = build(priority_report)

    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output_md.write_text(
        render_markdown(report),
        encoding="utf-8",
    )

    print("COSTARO STAGE 34: OK")
    print("Priority materials: 8")
    print("Technical source leads: 8")
    print("Independent quality verifications: 0")
    print("Tier approvals: 0")
    print("Published prices changed: 0")


if __name__ == "__main__":
    main()