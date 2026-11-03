"""COSTARO Stage 33: priority material quality evidence requirements.

Research-only technical requirements. This module never changes
published prices, material quantities, Flutter calculations or tier mappings.
"""

import json
from pathlib import Path


PROFILES = {
    "tileAdhesive": {
        "family": "chemical_systems",
        "nameRu": "Плиточный клей",
        "reference": "EN 12004-1:2017, where applicable",
        "checks": [
            (
                "adhesiveType",
                "Тип и техническое обозначение клея",
                "тип/класс",
                "Паспорт производителя с назначением и классификацией",
            ),
            (
                "adhesion",
                "Заявленные характеристики сцепления",
                "Н/мм²",
                "Документированные результаты применимого испытания",
            ),
            (
                "openTime",
                "Открытое время работы",
                "мин",
                "Технические данные производителя",
            ),
            (
                "substrateCompatibility",
                "Подходящие основания и типы плитки",
                "перечень",
                "Официальные условия применения",
            ),
            (
                "wetRoomSuitability",
                "Пригодность для влажных помещений",
                "подтверждение",
                "Документация о допустимых условиях эксплуатации",
            ),
        ],
    },

    "primer": {
        "family": "chemical_systems",
        "nameRu": "Грунтовка",
        "reference": "Product-specific manufacturer documentation",
        "checks": [
            (
                "primerType",
                "Точное назначение и тип грунтовки",
                "тип",
                "Технический паспорт продукта",
            ),
            (
                "substrates",
                "Допустимые виды основания",
                "перечень",
                "Официальная область применения",
            ),
            (
                "consumption",
                "Расход при определённых условиях",
                "л/м² или кг/м²",
                "Данные производителя с указанной единицей",
            ),
            (
                "dilution",
                "Допустимое разбавление",
                "пропорция",
                "Инструкция по приготовлению и нанесению",
            ),
            (
                "dryingConditions",
                "Высыхание и условия применения",
                "время/условия",
                "Инструкция производителя",
            ),
        ],
    },

    "gypsumPlaster": {
        "family": "surface_compounds",
        "nameRu": "Гипсовая штукатурка",
        "reference": "Applicable product-specific technical documentation",
        "checks": [
            (
                "roomUse",
                "Назначение и ограничения по влажности",
                "условия",
                "Официальная область применения",
            ),
            (
                "layerThickness",
                "Допустимая толщина слоя",
                "мм",
                "Технический паспорт производителя",
            ),
            (
                "consumption",
                "Расход с указанием толщины",
                "кг/м²",
                "Документированная норма для заданного слоя",
            ),
            (
                "strength",
                "Заявленные прочностные характеристики",
                "Н/мм²",
                "Применимый протокол испытания или декларация",
            ),
            (
                "substrates",
                "Совместимость с основанием",
                "перечень",
                "Инструкция по подготовке и нанесению",
            ),
        ],
    },

    "cementPlaster": {
        "family": "surface_compounds",
        "nameRu": "Цементная штукатурка",
        "reference": "Applicable product-specific technical documentation",
        "checks": [
            (
                "roomUse",
                "Назначение и условия влажности",
                "условия",
                "Официальная область применения",
            ),
            (
                "layerThickness",
                "Допустимая толщина слоя",
                "мм",
                "Технический паспорт производителя",
            ),
            (
                "consumption",
                "Расход для определённого слоя",
                "кг/м²",
                "Данные производителя с указанием толщины",
            ),
            (
                "strength",
                "Заявленная прочность раствора",
                "Н/мм²",
                "Декларация или применимое испытание",
            ),
            (
                "curing",
                "Условия выдерживания и высыхания",
                "время/условия",
                "Официальная инструкция по применению",
            ),
        ],
    },

    "tilePerM2": {
        "family": "floor_coverings",
        "nameRu": "Керамическая плитка",
        "reference": "EN 14411:2016, where applicable",
        "checks": [
            (
                "tileClassification",
                "Тип и классификация плитки",
                "класс/группа",
                "Маркировка и документация производителя",
            ),
            (
                "waterAbsorption",
                "Водопоглощение",
                "%",
                "Декларированный показатель и метод испытания",
            ),
            (
                "slipResistance",
                "Характеристики сопротивления скольжению",
                "класс/метод",
                "Декларация с указанным методом испытания",
            ),
            (
                "wearResistance",
                "Стойкость к предусмотренному износу",
                "класс/метод",
                "Сопоставимые результаты применимых испытаний",
            ),
            (
                "dimensions",
                "Размеры и толщина плитки",
                "мм",
                "Официальные размеры и допуски",
            ),
        ],
    },

    "laminatePerM2": {
        "family": "floor_coverings",
        "nameRu": "Ламинат",
        "reference": "EN 13329:2023, if within product scope",
        "checks": [
            (
                "useClass",
                "Класс и область применения",
                "класс",
                "Маркировка и технические данные производителя",
            ),
            (
                "thickness",
                "Толщина панели",
                "мм",
                "Паспорт изделия",
            ),
            (
                "wearResistance",
                "Заявленная стойкость к износу",
                "класс/метод",
                "Результат применимого испытания",
            ),
            (
                "moistureLimit",
                "Ограничения по воздействию влаги",
                "условия",
                "Официальная документация без предположения о водонепроницаемости",
            ),
            (
                "installation",
                "Совместимость с основанием и подложкой",
                "условия",
                "Инструкция по монтажу",
            ),
        ],
    },

    "electricalLightingCablePerM": {
        "family": "electrical_components",
        "nameRu": "Кабель освещения",
        "reference": "IEC 60228:2023 for applicable conductors",
        "checks": [
            (
                "conductorSection",
                "Номинальное сечение проводников",
                "мм²",
                "Паспорт кабеля и подтверждение применимой классификации",
            ),
            (
                "conductorMaterial",
                "Материал и число жил",
                "материал/шт.",
                "Заводская маркировка и паспорт",
            ),
            (
                "ratedVoltage",
                "Номинальное напряжение",
                "В",
                "Техническая маркировка производителя",
            ),
            (
                "insulation",
                "Изоляция и заявленные характеристики безопасности",
                "тип/класс",
                "Официальные документы и применимые испытания",
            ),
            (
                "installationScope",
                "Допустимый способ и условия прокладки",
                "условия",
                "Документация производителя и применимые требования монтажа",
            ),
        ],
    },

    "electricalSocketCablePerM": {
        "family": "electrical_components",
        "nameRu": "Кабель розеточной линии",
        "reference": "IEC 60228:2023 for applicable conductors",
        "checks": [
            (
                "conductorSection",
                "Номинальное сечение проводников",
                "мм²",
                "Паспорт кабеля и подтверждение применимой классификации",
            ),
            (
                "conductorMaterial",
                "Материал и число жил",
                "материал/шт.",
                "Маркировка и документация производителя",
            ),
            (
                "ratedVoltage",
                "Номинальное напряжение",
                "В",
                "Технический паспорт",
            ),
            (
                "insulation",
                "Тип изоляции и характеристики безопасности",
                "тип/класс",
                "Официальные документы и применимые испытания",
            ),
            (
                "installationScope",
                "Пригодность для предполагаемой розеточной линии",
                "условия",
                "Документация и проверка применимых требований монтажа",
            ),
        ],
    },
}


PRINCIPLE = {
    "qualityDeterminesTier": True,
    "verifiedMarketPriceDeterminesCost": True,
    "priceAloneMayNeverDetermineTier": True,
    "unverifiedQualityMustRemainUnclassified": True,
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def build(catalog, family_report, profiles=None):
    definitions = PROFILES if profiles is None else profiles

    require(
        catalog.get("schemaVersion") == 1
        and catalog.get("country") == "MD"
        and catalog.get("currency") == "MDL"
        and catalog.get("status") == "draft"
        and catalog.get("automaticUpdatesEnabled") is False,
        "Unexpected or unsafe catalog",
    )

    prices = catalog.get("materialPrices")

    require(
        isinstance(prices, dict) and len(prices) == 41,
        "Expected exactly 41 materials",
    )

    require(
        family_report.get("schemaVersion") == 1
        and family_report.get("policyVersion") == 1
        and family_report.get("status")
            == "material_family_criteria_research_only"
        and family_report.get("principle") == PRINCIPLE,
        "Unsafe Stage 32 source report",
    )

    for flag in (
        "publishedPricesChanged",
        "flutterCalculationsChanged",
        "tierMappingsChanged",
        "automaticPublicationEnabled",
    ):
        require(
            family_report.get(flag) is False,
            "Unsafe source flag: " + flag,
        )

    summary = family_report.get("summary", {})

    require(
        summary.get("catalogMaterials") == 41
        and summary.get("technicalFamilies") == 8
        and summary.get("materialsAssignedExactlyOnce") == 41
        and summary.get("materialsUnassigned") == 0
        and summary.get("materialsMultiplyAssigned") == 0
        and summary.get("materialsWithExistingDetailedPilotCriteria") == 2
        and summary.get("materialsAwaitingIndividualDetailedCriteria") == 39
        and summary.get("qualityTiersApproved") == 0
        and summary.get("approvedForPublication") == 0,
        "Stage 32 coverage or approval state changed",
    )

    source_rows = family_report.get("materialCoverage")

    require(
        isinstance(source_rows, list) and len(source_rows) == 41,
        "Missing Stage 32 material coverage",
    )

    source_by_key = {}

    for row in source_rows:
        require(isinstance(row, dict), "Invalid source material")

        key = row.get("catalogMaterialKey")

        require(
            isinstance(key, str) and key not in source_by_key,
            "Duplicate or invalid source material",
        )

        require(
            row.get("qualityTierApproved") is False
            and row.get("approvedForPublication") is False,
            "Unexpected source material approval",
        )

        source_by_key[key] = row

    require(
        set(source_by_key) == set(prices),
        "Stage 32 catalog keys do not match",
    )

    pilot_keys = {
        key for key, row in source_by_key.items()
        if row.get("individualCriteriaStatus") == "pilot_defined"
    }

    require(
        pilot_keys == {"finishPutty", "interiorPaint"},
        "Unexpected existing pilot criteria",
    )

    require(
        all(
            row.get("individualCriteriaStatus")
            in ("pilot_defined", "material_specific_criteria_pending")
            for row in source_rows
        ),
        "Unknown criteria status",
    )

    require(
        isinstance(definitions, dict)
        and len(definitions) == 8,
        "Exactly eight new material profiles are required",
    )

    require(
        not (set(definitions) & pilot_keys),
        "Existing Stage 31 pilots must not be duplicated",
    )

    material_profiles = []
    total_checks = 0

    for key, definition in definitions.items():
        require(
            key in source_by_key,
            "Unknown priority material: " + key,
        )

        require(
            definition.get("family")
            == source_by_key[key].get("technicalFamilyId"),
            "Technical family mismatch: " + key,
        )

        checks = definition.get("checks")

        require(
            isinstance(checks, (list, tuple))
            and len(checks) >= 5,
            "At least five technical checks required: " + key,
        )

        seen = set()
        rows = []

        for check in checks:
            require(
                isinstance(check, (tuple, list))
                and len(check) == 4,
                "Invalid check structure: " + key,
            )

            code, name, unit, evidence = check

            require(
                all(isinstance(v, str) and v.strip() for v in check),
                "Empty technical check: " + key,
            )

            require(
                code.isidentifier() and code not in seen,
                "Duplicate or invalid technical check: " + code,
            )

            seen.add(code)

            rows.append({
                "criterionId": code,
                "criterionRu": name,
                "comparisonUnit": unit,
                "requiredEvidenceRu": evidence,
                "verifiedValue": None,
                "evidenceProvided": False,
                "evidenceReviewed": False,
                "evidenceStatus": "awaiting_objective_evidence",
            })

        total_checks += len(rows)

        material_profiles.append({
            "catalogMaterialKey": key,
            "technicalFamilyId": definition["family"],
            "materialNameRu": definition["nameRu"],
            "technicalReference": definition["reference"],
            "referenceDoesNotAssignTier": True,
            "technicalChecks": rows,
            "qualityTier": "unclassified",
            "qualityTierApproved": False,
            "approvedForPublication": False,
        })

    material_profiles.sort(
        key=lambda item: item["catalogMaterialKey"]
    )

    defined_total = len(pilot_keys) + len(material_profiles)

    return {
        "schemaVersion": 1,
        "policyVersion": 1,
        "status": "priority_quality_evidence_requirements_only",
        "principle": dict(PRINCIPLE),
        "summary": {
            "catalogMaterials": 41,
            "existingDetailedPilots": 2,
            "newPriorityProfiles": 8,
            "totalMaterialsWithIndividualCriteria": defined_total,
            "materialsStillAwaitingIndividualCriteria": 41 - defined_total,
            "technicalEvidenceRequirements": total_checks,
            "verifiedEvidenceRequirements": 0,
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "materials": material_profiles,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
        "automaticTierAssignmentEnabled": False,
        "automaticPublicationEnabled": False,
    }


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — этап 33: требования к качеству материалов",
        "",
        "**Исследовательский отчёт. Качество и цены не утверждаются.**",
        "",
        "## Покрытие каталога",
        "",
        f"- Материалов каталога: {summary['catalogMaterials']}",
        f"- Ранее определённых пилотных критериев: {summary['existingDetailedPilots']}",
        f"- Новых подробных карточек: {summary['newPriorityProfiles']}",
        (
            "- Всего материалов с индивидуальными критериями: "
            f"{summary['totalMaterialsWithIndividualCriteria']}"
        ),
        (
            "- Осталось определить индивидуальные критерии: "
            f"{summary['materialsStillAwaitingIndividualCriteria']}"
        ),
        (
            "- Пунктов для сбора технических доказательств: "
            f"{summary['technicalEvidenceRequirements']}"
        ),
        "- Проверенных технических доказательств: 0",
        "- Утверждённых категорий качества: 0",
        "- Разрешений на публикацию: 0",
        "",
    ]

    for material in report["materials"]:
        lines.extend([
            f"## {material['materialNameRu']}",
            "",
            f"Ключ каталога: `{material['catalogMaterialKey']}`.",
            "",
            (
                "Технический ориентир: "
                + material["technicalReference"]
            ),
            "",
            "| Характеристика | Единица | Какие доказательства нужны |",
            "|---|---|---|",
        ])

        for check in material["technicalChecks"]:
            lines.append(
                f"| {check['criterionRu']} "
                f"| {check['comparisonUnit']} "
                f"| {check['requiredEvidenceRu']} |"
            )

        lines.extend([
            "",
            "**Статус: документы и сопоставимые показатели ожидаются.**",
            "",
        ])

    lines.extend([
        "## Правило безопасности",
        "",
        "- Цена не является доказательством качества.",
        "- Наличие технического стандарта не назначает категорию автоматически.",
        "- Неизвестные характеристики нельзя заменять предположениями.",
        "- Для утверждения категории нужны сопоставимые доказательства "
        "и отдельное решение после проверки.",
        "- Цены, нормы расхода, формулы Flutter и действующие соответствия "
        "ценовым категориям не изменялись.",
        "",
    ])

    return "\n".join(lines)


def main():
    catalog = json.loads(
        Path("prices.json").read_text(encoding="utf-8")
    )

    family_report = json.loads(
        Path("material_family_criteria.json").read_text(encoding="utf-8")
    )

    output_json = Path("priority_material_criteria.json")
    output_md = Path("priority_material_criteria_RU.md")

    if output_json.exists() or output_md.exists():
        raise FileExistsError("Stage 33 report already exists")

    report = build(catalog, family_report)

    output_json.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output_md.write_text(
        render_markdown(report),
        encoding="utf-8",
    )

    print("COSTARO STAGE 33: OK")
    print("Individual criteria profiles: 10/41")
    print("New priority profiles: 8")
    print("Technical requirements: 40")
    print("Verified evidence: 0")
    print("Tier approvals: 0")
    print("Price and Flutter calculation changes: 0")


if __name__ == "__main__":
    main()