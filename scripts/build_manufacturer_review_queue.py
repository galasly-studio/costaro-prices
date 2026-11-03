"""COSTARO Stage 35: guarded manufacturer evidence review queue.

Generate manual research tasks from unapproved technical requirements
and manufacturer source leads. No quality approval or price publication.
"""

import json
from pathlib import Path


CRITICAL_CRITERIA = {
    "tileAdhesive": {"adhesion", "wetRoomSuitability"},
    "primer": {"substrates", "consumption"},
    "gypsumPlaster": {"roomUse", "strength"},
    "cementPlaster": {"roomUse", "strength"},
    "tilePerM2": {"waterAbsorption", "slipResistance"},
    "laminatePerM2": {"moistureLimit", "wearResistance"},
    "electricalLightingCablePerM": {"installationScope", "insulation"},
    "electricalSocketCablePerM": {"installationScope", "insulation"},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def validate_safety(report, expected_status):
    require(
        report.get("schemaVersion") == 1
        and report.get("status") == expected_status,
        "Unexpected research report status",
    )

    for flag in (
        "publishedPricesChanged",
        "flutterCalculationsChanged",
        "tierMappingsChanged",
        "automaticTierAssignmentEnabled",
        "automaticPublicationEnabled",
    ):
        require(
            report.get(flag) is False,
            "Unsafe research flag: " + flag,
        )


def build(priority_report, source_report):
    validate_safety(
        priority_report,
        "priority_quality_evidence_requirements_only",
    )

    validate_safety(
        source_report,
        "manufacturer_source_leads_research_only",
    )

    priority_summary = priority_report.get("summary", {})
    source_summary = source_report.get("summary", {})

    require(
        priority_summary.get("catalogMaterials") == 41
        and priority_summary.get("newPriorityProfiles") == 8
        and priority_summary.get("technicalEvidenceRequirements") == 40
        and priority_summary.get("verifiedEvidenceRequirements") == 0
        and priority_summary.get("qualityTiersApproved") == 0
        and priority_summary.get("approvedForPublication") == 0,
        "Unexpected priority evidence state",
    )

    require(
        source_summary.get("priorityMaterials") == 8
        and source_summary.get("candidateTechnicalSources") == 8
        and source_summary.get("independentlyVerifiedClaims") == 0
        and source_summary.get("verifiedMoldovaRetailSkuMappings") == 0
        and source_summary.get("qualityTiersApproved") == 0
        and source_summary.get("approvedForPublication") == 0,
        "Unexpected manufacturer source state",
    )

    priority_rows = priority_report.get("materials")
    source_rows = source_report.get("candidates")

    require(
        isinstance(priority_rows, list)
        and isinstance(source_rows, list)
        and len(priority_rows) == 8
        and len(source_rows) == 8,
        "Expected eight materials in both reports",
    )

    priority = {}
    sources = {}

    for row in priority_rows:
        require(isinstance(row, dict), "Invalid priority material")

        key = row.get("catalogMaterialKey")

        require(
            isinstance(key, str) and key not in priority,
            "Duplicate or invalid priority material",
        )

        require(
            row.get("qualityTier") == "unclassified"
            and row.get("qualityTierApproved") is False
            and row.get("approvedForPublication") is False,
            "Unexpected priority quality approval",
        )

        criteria = row.get("technicalChecks")

        require(
            isinstance(criteria, list) and len(criteria) == 5,
            "Expected five technical criteria",
        )

        criteria_by_id = {}

        for criterion in criteria:
            require(isinstance(criterion, dict), "Invalid criterion")

            criterion_id = criterion.get("criterionId")

            require(
                isinstance(criterion_id, str)
                and criterion_id not in criteria_by_id,
                "Duplicate criterion ID",
            )

            require(
                criterion.get("verifiedValue") is None
                and criterion.get("evidenceProvided") is False
                and criterion.get("evidenceReviewed") is False,
                "Unexpected verified technical evidence",
            )

            criteria_by_id[criterion_id] = criterion

        priority[key] = {
            "nameRu": row["materialNameRu"],
            "criteria": criteria_by_id,
        }

    for row in source_rows:
        require(isinstance(row, dict), "Invalid manufacturer lead")

        key = row.get("catalogMaterialKey")

        require(
            isinstance(key, str) and key not in sources,
            "Duplicate manufacturer lead",
        )

        require(
            row.get("qualityTierApproved") is False
            and row.get("approvedForPublication") is False
            and row.get("exactRetailSkuInMoldovaVerified") is False
            and row.get("independentQualityComparisonVerified") is False
            and row.get("sourceUrlCheckedByWorkflow") is False,
            "Unexpected source approval",
        )

        require(
            row.get("sourceSpecificity") in (
                "exact_model",
                "product_line",
                "product_type",
            ),
            "Invalid document specificity",
        )

        sources[key] = row

    require(
        set(priority) == set(sources)
        and set(priority) == set(CRITICAL_CRITERIA),
        "Technical materials and source leads do not match",
    )

    tasks = []
    coverage = []

    missing_count = 0
    claim_count = 0
    sku_count = 0
    refresh_count = 0

    def add_task(priority_number, task_type, key, criterion_id, action, url):
        tasks.append({
            "priority": priority_number,
            "taskType": task_type,
            "catalogMaterialKey": key,
            "criterionId": criterion_id,
            "nextActionRu": action,
            "sourceUrl": url,
            "evidenceApproved": False,
            "qualityTierApproved": False,
            "priceChangeAllowed": False,
            "approvedForPublication": False,
        })

    for key in sorted(priority):
        profile = priority[key]
        lead = sources[key]
        url = lead.get("sourceUrl")

        require(
            isinstance(url, str)
            and url.startswith("https://"),
            "Missing HTTPS technical source",
        )

        statements = lead.get("sourceClaims")

        require(
            isinstance(statements, list),
            "Missing manufacturer claims",
        )

        claims_by_id = {}

        for statement in statements:
            require(
                isinstance(statement, dict),
                "Invalid manufacturer statement",
            )

            criterion_id = statement.get("criterionId")

            require(
                criterion_id in profile["criteria"]
                and criterion_id not in claims_by_id,
                "Duplicate or unknown source criterion",
            )

            require(
                isinstance(statement.get("manufacturerStatementRu"), str)
                and bool(statement["manufacturerStatementRu"].strip())
                and statement.get("independentlyVerified") is False
                and statement.get("approvedAsQualityEvidence") is False,
                "Unexpected approved manufacturer statement",
            )

            claims_by_id[criterion_id] = statement

        expected_missing = len(profile["criteria"]) - len(claims_by_id)

        require(
            lead.get("missingIndividualEvidenceCount") == expected_missing,
            "Manufacturer claim count does not match criteria",
        )

        claim_count += len(claims_by_id)
        missing_count += expected_missing
        sku_count += 1

        specificity = lead["sourceSpecificity"]

        identity_priority = 1 if specificity != "exact_model" else 2

        add_task(
            identity_priority,
            "verify_exact_moldova_sku",
            key,
            None,
            "Проверить точный артикул, упаковку, наличие в Молдове "
            "и соответствие технического документа именно этому товару.",
            url,
        )

        for criterion_id, criterion in profile["criteria"].items():
            if criterion_id in claims_by_id:
                add_task(
                    2,
                    "review_manufacturer_statement",
                    key,
                    criterion_id,
                    "Открыть первичный документ, проверить исходную "
                    "характеристику, единицу измерения, условия применения "
                    "и достаточность доказательств.",
                    url,
                )
            else:
                critical = criterion_id in CRITICAL_CRITERIA[key]

                add_task(
                    1 if critical else 2,
                    "find_missing_criterion",
                    key,
                    criterion_id,
                    "Найти первичную документацию или применимый "
                    "протокол испытаний для характеристики: "
                    + criterion["criterionRu"],
                    url,
                )

        if lead.get("sourceNeedsManualRefresh") is True:
            refresh_count += 1

            add_task(
                1,
                "refresh_technical_source",
                key,
                None,
                "Повторно проверить доступность и актуальность "
                "документа производителя.",
                url,
            )
        else:
            require(
                lead.get("sourceNeedsManualRefresh") is False,
                "Unknown source refresh status",
            )

        coverage.append({
            "catalogMaterialKey": key,
            "sourceSpecificity": specificity,
            "manufacturerStatements": len(claims_by_id),
            "criteriaWithoutManufacturerStatements": expected_missing,
            "moldovaSkuVerified": False,
            "qualityTierApproved": False,
            "approvedForPublication": False,
        })

    require(
        claim_count
        == source_summary.get("manufacturerStatementsRecorded"),
        "Manufacturer statement total differs from source",
    )

    require(
        refresh_count
        == source_summary.get("sourcesNeedingManualRefresh"),
        "Source refresh count mismatch",
    )

    require(
        claim_count + missing_count == 40,
        "Technical coverage does not equal 40 requirements",
    )

    task_order = {
        "refresh_technical_source": 0,
        "verify_exact_moldova_sku": 1,
        "find_missing_criterion": 2,
        "review_manufacturer_statement": 3,
    }

    tasks.sort(
        key=lambda row: (
            row["priority"],
            task_order[row["taskType"]],
            row["catalogMaterialKey"],
            row["criterionId"] or "",
        )
    )

    require(
        len(tasks)
        == sku_count + missing_count + claim_count + refresh_count,
        "Manual task count mismatch",
    )

    return {
        "schemaVersion": 1,
        "status": "manufacturer_manual_evidence_queue_only",
        "summary": {
            "priorityMaterials": 8,
            "technicalRequirements": 40,
            "manufacturerStatementsNeedingReview": claim_count,
            "missingManufacturerStatements": missing_count,
            "skuAndMoldovaAvailabilityTasks": sku_count,
            "staleSourceRefreshTasks": refresh_count,
            "totalManualResearchTasks": len(tasks),
            "independentlyVerifiedEvidence": 0,
            "approvedQualityTiers": 0,
            "approvedForPublication": 0,
        },
        "coverage": coverage,
        "tasks": tasks,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
        "automaticTierAssignmentEnabled": False,
        "automaticPublicationEnabled": False,
    }


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — этап 35: очередь проверки технических доказательств",
        "",
        "**Только ручное исследование. Цены и категории не утверждаются.**",
        "",
        "## Результат",
        "",
        f"- Материалов: **{summary['priorityMaterials']}**",
        f"- Технических требований: **{summary['technicalRequirements']}**",
        (
            "- Заявлений производителей для проверки: "
            f"**{summary['manufacturerStatementsNeedingReview']}**"
        ),
        (
            "- Недостающих характеристик: "
            f"**{summary['missingManufacturerStatements']}**"
        ),
        (
            "- Проверок артикула и доступности в Молдове: "
            f"**{summary['skuAndMoldovaAvailabilityTasks']}**"
        ),
        (
            "- Всего исследовательских задач: "
            f"**{summary['totalManualResearchTasks']}**"
        ),
        "- Независимо подтверждённых характеристик: **0**",
        "- Утверждённых категорий качества: **0**",
        "",
        "## Полнота сведений по материалам",
        "",
        "| Материал | Заявления | Недостаёт | Точность источника |",
        "|---|---:|---:|---|",
    ]

    for row in report["coverage"]:
        lines.append(
            f"| `{row['catalogMaterialKey']}` "
            f"| {row['manufacturerStatements']} "
            f"| {row['criteriaWithoutManufacturerStatements']} "
            f"| {row['sourceSpecificity']} |"
        )

    lines.extend([
        "",
        "## Очередь ручной проверки",
        "",
        "| Приоритет | Материал | Тип задачи | Следующее действие |",
        "|---:|---|---|---|",
    ])

    for task in report["tasks"]:
        lines.append(
            f"| {task['priority']} "
            f"| `{task['catalogMaterialKey']}` "
            f"| `{task['taskType']}` "
            f"| {task['nextActionRu']} |"
        )

    lines.extend([
        "",
        "## Ограничения",
        "",
        "- Заявления производителя не считаются независимой проверкой.",
        "- Доступность конкретного артикула в Молдове требует подтверждения.",
        "- Категории бюджет/стандарт/премиум не присваиваются автоматически.",
        "- Для электрических изделий необходима проверка применимых "
        "требований проектирования и монтажа.",
        "- Действующие цены, нормы расхода и формулы COSTARO не изменены.",
        "",
    ])

    return "\n".join(lines)


def main():
    priority_report = json.loads(
        Path("priority_material_criteria.json").read_text(
            encoding="utf-8"
        )
    )

    source_report = json.loads(
        Path("manufacturer_evidence_leads.json").read_text(
            encoding="utf-8"
        )
    )

    output_json = Path("manufacturer_review_queue.json")
    output_md = Path("manufacturer_review_queue_RU.md")

    if output_json.exists() or output_md.exists():
        raise FileExistsError("Stage 35 report already exists")

    report = build(priority_report, source_report)

    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output_md.write_text(
        render_markdown(report),
        encoding="utf-8",
    )

    summary = report["summary"]

    print("COSTARO STAGE 35: OK")
    print("Priority materials: 8")
    print(
        "Manufacturer statements for review:",
        summary["manufacturerStatementsNeedingReview"],
    )
    print(
        "Missing technical statements:",
        summary["missingManufacturerStatements"],
    )
    print("Manual research tasks:", summary["totalManualResearchTasks"])
    print("Approved quality tiers: 0")
    print("Published price changes: 0")


if __name__ == "__main__":
    main()