#!/usr/bin/env python3
"""Complete the research-only technical-criteria coverage of COSTARO materials.

No changes to published prices, consumption norms, Flutter calculations,
budget/standard/premium assignments, or publication permissions.
"""

from __future__ import annotations

import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


# Four material-specific questions for every previously uncovered catalog key.
# These are QUESTIONS requiring evidence, not verified product properties.

NEW_CRITERIA = {
    "decorativePlaster": (
        "Совместимость с основанием и подготовкой поверхности",
        "Тип декоративной фактуры и размер зерна",
        "Расход при выбранной фактуре и способе нанесения",
        "Допустимая влажность и условия эксплуатации",
    ),
    "startPutty": (
        "Допустимые основания и тип последующей отделки",
        "Минимальная и максимальная толщина слоя",
        "Расход при документированной толщине",
        "Условия высыхания и возможность последующей обработки",
    ),
    "floorScreedMix": (
        "Допустимая толщина стяжки и тип основания",
        "Прочность и назначение по эксплуатационной нагрузке",
        "Расход сухой смеси на толщину слоя",
        "Сроки выдерживания перед устройством покрытия",
    ),
    "selfLevelingFloorMix": (
        "Диапазон допустимой толщины выравнивания",
        "Совместимость с основанием и грунтовкой",
        "Расход при установленной толщине",
        "Время работы со смесью и готовность к покрытию",
    ),
    "grout": (
        "Допустимая ширина межплиточного шва",
        "Водопоглощение и условия влажной эксплуатации",
        "Совместимость с типом плитки и основанием",
        "Стойкость к очистке и условиям использования",
    ),
    "wallpaperGlue": (
        "Совместимость с типом и массой обоев",
        "Расход и площадь покрытия одной упаковкой",
        "Условия нанесения и время корректировки",
        "Допустимые основания и влажностные ограничения",
    ),
    "floorWaterproofing": (
        "Допустимые основания и области применения",
        "Требуемая толщина сухого слоя и число нанесений",
        "Стойкость к предусмотренному воздействию воды",
        "Время выдерживания и совместимость с плиточным клеем",
    ),
    "wallpaper": (
        "Материал покрытия и совместимость с клеем",
        "Размеры рулона и полезная площадь покрытия",
        "Стойкость к очистке и истиранию",
        "Пригодность для помещения с выбранной влажностью",
    ),
    "laminateUnderlayPerM2": (
        "Толщина подложки и совместимость с замковым покрытием",
        "Сопротивление сжатию и длительной нагрузке",
        "Заявленные акустические характеристики",
        "Необходимость и наличие защиты от влаги",
    ),
    "linoleumPerM2": (
        "Тип материала и заявленная область применения",
        "Общая толщина и эксплуатационная износостойкость",
        "Влагостойкость и ограничения по помещению",
        "Требования к основанию и способу укладки",
    ),
    "vinylPerM2": (
        "Тип укладки: клеевая или замковая технология",
        "Толщина защитного слоя и эксплуатационная нагрузка",
        "Влагостойкость и ограничения эксплуатации",
        "Ровность основания и совместимость с подложкой",
    ),
    "electricalLightingConnectorPerPoint": (
        "Номинальные напряжение и ток соединителя",
        "Допустимое сечение и материал проводников",
        "Тип фиксации и допустимые способы монтажа",
        "Условия защиты и подтверждение соответствия",
    ),
    "electricalSocketPerPiece": (
        "Номинальный ток и напряжение розетки",
        "Наличие защитного контакта и тип подключения",
        "Степень защиты и условия установки",
        "Совместимость с монтажной коробкой",
    ),
    "electricalSubboxPerPiece": (
        "Диаметр и глубина монтажной коробки",
        "Предназначение для соответствующего материала стены",
        "Совместимость с электроустановочными изделиями",
        "Огнестойкость и ограничения условий монтажа",
    ),
    "electricalSwitchPerPiece": (
        "Номинальная электрическая нагрузка",
        "Тип коммутации и число клавиш или линий",
        "Степень защиты и допустимая влажность",
        "Совместимость с монтажной коробкой и проводкой",
    ),
    "gypsumBoardCeiling": (
        "Толщина и геометрические параметры листа",
        "Тип листа и пригодность для влажных помещений",
        "Ограничения применения в потолочной системе",
        "Подтверждённые противопожарные свойства при необходимости",
    ),
    "ceilingCdProfile": (
        "Сечение и геометрические размеры профиля",
        "Толщина металла и механические характеристики",
        "Антикоррозионное покрытие",
        "Совместимость с подвесами и соединителями системы",
    ),
    "ceilingUdProfile": (
        "Габариты направляющего профиля",
        "Толщина металла и геометрические допуски",
        "Защитное покрытие от коррозии",
        "Совместимость с основными профилями и креплением",
    ),
    "ceilingJointTape": (
        "Тип армирующего материала",
        "Совместимость со шпаклёвкой для швов",
        "Применимость для требуемого типа соединений",
        "Условия эксплуатации и устойчивость к деформациям",
    ),
    "ceilingBaseAnchorPerPiece": (
        "Тип и прочность несущего основания",
        "Подтверждённая допустимая нагрузка анкера",
        "Размеры и требуемая глубина закрепления",
        "Условия эксплуатации и защита от коррозии",
    ),
    "ceilingCrossConnectorPerPiece": (
        "Совместимость с геометрией потолочного профиля",
        "Толщина металла и допустимая нагрузка соединения",
        "Способ фиксации пересечения профилей",
        "Защитное покрытие и область применения",
    ),
    "ceilingDirectHangerPerPiece": (
        "Допустимая нагрузка подвеса",
        "Габариты и пределы регулирования высоты",
        "Толщина металла и коррозионная стойкость",
        "Совместимость с крепежом и несущим основанием",
    ),
    "ceilingDrywallScrews": (
        "Назначение для требуемого числа слоёв гипсокартона",
        "Диаметр и длина крепежа",
        "Допустимая толщина металлического основания",
        "Защитное покрытие и условия эксплуатации",
    ),
    "ceilingExtensionConnectorPerPiece": (
        "Совместимость с сечением потолочного профиля",
        "Длина соединения и фиксация элементов",
        "Материал и толщина соединителя",
        "Допустимая область применения в системе",
    ),
    "ceilingFrameFastenersPerM2": (
        "Назначение крепления и тип несущего основания",
        "Доказанная несущая способность соединения",
        "Размеры и ограничения монтажа",
        "Системная совместимость и шаг установки",
    ),
    "ceilingMetalScrews": (
        "Допустимая толщина соединяемых металлических профилей",
        "Диаметр, длина и тип наконечника",
        "Материал и антикоррозионная защита",
        "Совместимость с соединяемыми элементами",
    ),
    "ceilingUdFastenerPerPiece": (
        "Тип основания для крепления направляющего профиля",
        "Размеры крепежа и глубина установки",
        "Подтверждённая несущая способность",
        "Стойкость к коррозии и ограничения применения",
    ),
    "mdfSkirtingPiece": (
        "Габариты и полезная длина плинтуса",
        "Влагостойкость материала и ограничения помещения",
        "Тип декоративной поверхности",
        "Способ крепления и совместимость с фурнитурой",
    ),
    "pvcSkirtingPiece": (
        "Габариты и полезная длина профиля",
        "Ударостойкость и температурные ограничения",
        "Наличие и размеры кабельного канала",
        "Совместимость с углами и соединительными деталями",
    ),
    "woodSkirtingPiece": (
        "Порода древесины и параметры материала",
        "Влажность древесины и ограничения применения",
        "Габариты и тип защитно-декоративного покрытия",
        "Способ монтажа и совместимая фурнитура",
    ),
    "skirtingAccessoryPerPiece": (
        "Тип аксессуара: угол, заглушка или соединитель",
        "Совместимость с конкретной серией плинтуса",
        "Размеры и геометрия соединения",
        "Материал, способ фиксации и условия эксплуатации",
    ),
}

EXPECTED_NEW_MATERIALS = 31
EXPECTED_TOTAL_MATERIALS = 41
EXPECTED_PRIORITY_MATERIALS = 8
EXPECTED_LEGACY_PILOTS = 2


def load_json(filename):
    return json.loads(Path(filename).read_text(encoding="utf-8"))


def _check_unapproved(item):
    if item.get("approvedForPublication"):
        raise ValueError("Unexpected publication approval in research input")
    if item.get("qualityTierApproved"):
        raise ValueError("Unexpected quality approval in research input")


def build_report(families, priorities, previous_review, source_health):
    family_rows = families["families"]

    all_keys = [
        key
        for group in family_rows
        for key in group["catalogMaterialKeys"]
    ]

    if (
        len(all_keys) != EXPECTED_TOTAL_MATERIALS
        or len(set(all_keys)) != len(all_keys)
        or families["summary"]["catalogMaterials"] != len(all_keys)
    ):
        raise ValueError("Expected 41 unique catalog material keys")

    priority_rows = priorities["materials"]

    priority_by_key = {
        row["catalogMaterialKey"]: row
        for row in priority_rows
    }

    if (
        len(priority_rows) != EXPECTED_PRIORITY_MATERIALS
        or len(priority_by_key) != len(priority_rows)
    ):
        raise ValueError("Unexpected priority-material coverage")

    pilots = {
        row["catalogMaterialKey"]
        for row in previous_review["materials"]
        if row["detailedCriteriaStatus"] == "pilot_defined"
    }

    if len(pilots) != EXPECTED_LEGACY_PILOTS:
        raise ValueError("Unexpected legacy-pilot coverage")

    if pilots & set(priority_by_key):
        raise ValueError("Pilot and priority coverage overlap")

    missing = set(all_keys) - set(priority_by_key) - pilots

    if (
        len(missing) != EXPECTED_NEW_MATERIALS
        or missing != set(NEW_CRITERIA)
    ):
        raise ValueError(
            "Material-specific criteria do not match the uncovered catalog"
        )

    health_rows = source_health["priorityMaterials"]

    health_by_key = {
        row["catalogMaterialKey"]: row
        for row in health_rows
    }

    if set(health_by_key) != set(priority_by_key):
        raise ValueError("Stage 39 source coverage does not match priorities")

    pilot_products = {}

    for row in previous_review["products"]:
        _check_unapproved(row)

        key = row["catalogMaterialKey"]
        factors = row["technicalFactors"]

        if key in pilot_products and pilot_products[key] != factors:
            raise ValueError("Conflicting legacy-pilot criteria")

        pilot_products[key] = factors

    if set(pilot_products) != pilots:
        raise ValueError("Legacy technical-factor records are incomplete")

    for row in priority_rows:
        _check_unapproved(row)

        for check in row["technicalChecks"]:
            if (
                check.get("evidenceProvided")
                or check.get("evidenceReviewed")
                or check.get("verifiedValue") is not None
            ):
                raise ValueError(
                    "Verified technical evidence needs separate authorization"
                )

    family_by_key = {
        key: group["familyId"]
        for group in family_rows
        for key in group["catalogMaterialKeys"]
    }

    profiles = []
    new_profiles = []
    tasks = []

    for key in sorted(all_keys):
        if key in pilots:
            factors = pilot_products[key]

            profile = {
                "catalogMaterialKey": key,
                "technicalFamilyId": family_by_key[key],
                "criteriaOrigin": "existing_quality_first_pilot",
                "criteriaStatus": "defined_not_verified",
                "technicalCriteria": [
                    {
                        "criterionId": f"pilot_{index}",
                        "criterionRu": label,
                        "requiredEvidenceRu": (
                            "Применимые результаты испытаний, документация "
                            "для точного товара и независимое сравнение"
                        ),
                        "verifiedValue": None,
                        "independentlyVerified": False,
                    }
                    for index, label in enumerate(factors, 1)
                ],
            }

        elif key in priority_by_key:
            original = priority_by_key[key]

            profile = {
                "catalogMaterialKey": key,
                "technicalFamilyId": family_by_key[key],
                "criteriaOrigin": "existing_priority_profile",
                "criteriaStatus": "defined_not_verified",
                "stage39SourceStatus": health_by_key[key]["sourceStatus"],
                "technicalCriteria": [
                    {
                        "criterionId": check["criterionId"],
                        "criterionRu": check["criterionRu"],
                        "requiredEvidenceRu": check["requiredEvidenceRu"],
                        "verifiedValue": None,
                        "independentlyVerified": False,
                    }
                    for check in original["technicalChecks"]
                ],
            }

        else:
            checks = []

            for index, label in enumerate(NEW_CRITERIA[key], 1):
                criterion_id = f"specific_{index}"

                check = {
                    "criterionId": criterion_id,
                    "criterionRu": label,
                    "requiredEvidenceRu": (
                        "Актуальная документация производителя, "
                        "привязанная к точному товару и упаковке. "
                        "Для утверждения категории качества требуется "
                        "отдельная объективная сравнительная проверка."
                    ),
                    "verifiedValue": None,
                    "evidenceProvided": False,
                    "evidenceReviewed": False,
                    "independentlyVerified": False,
                }

                checks.append(check)

                tasks.append(
                    {
                        "catalogMaterialKey": key,
                        "technicalFamilyId": family_by_key[key],
                        "criterionId": criterion_id,
                        "criterionRu": label,
                        "nextActionRu": (
                            "Найти применимый технический документ, "
                            "сопоставить точный товар и упаковку, "
                            "проверить пригодность для условий COSTARO. "
                            "Не утверждать качество только по цене."
                        ),
                        "evidenceStatus": "awaiting_documented_review",
                        "qualityTierApproved": False,
                        "approvedForPublication": False,
                    }
                )

            profile = {
                "catalogMaterialKey": key,
                "technicalFamilyId": family_by_key[key],
                "criteriaOrigin": "stage40_new_specific_profile",
                "criteriaStatus": "defined_not_verified",
                "technicalCriteria": checks,
            }

            new_profiles.append(profile)

        profile["qualityTier"] = "unclassified"
        profile["qualityTierApproved"] = False
        profile["approvedForPublication"] = False

        profiles.append(profile)

    if len(profiles) != EXPECTED_TOTAL_MATERIALS:
        raise ValueError("Incomplete material criteria report")

    if len(new_profiles) != EXPECTED_NEW_MATERIALS:
        raise ValueError("Incomplete new individual profiles")

    if any(len(row["technicalCriteria"]) != 4 for row in new_profiles):
        raise ValueError("Every new profile needs four technical criteria")

    if len(tasks) != EXPECTED_NEW_MATERIALS * 4:
        raise ValueError("Unexpected manual research task coverage")

    source_exceptions = [
        {
            "catalogMaterialKey": row["catalogMaterialKey"],
            "sourceStatus": row["sourceStatus"],
        }
        for row in health_rows
        if row["sourceStatus"] != "reachable_format_only"
    ]

    family_coverage = []

    for group in family_rows:
        keys = set(group["catalogMaterialKeys"])

        family_coverage.append(
            {
                "familyId": group["familyId"],
                "titleRu": group["titleRu"],
                "catalogMaterials": len(keys),
                "newProfiles": len(keys & set(NEW_CRITERIA)),
                "priorityProfiles": len(keys & set(priority_by_key)),
                "legacyPilots": len(keys & pilots),
            }
        )

    summary = {
        "catalogMaterials": len(all_keys),
        "materialsWithIndividualCriteria": len(profiles),
        "technicalFamilies": len(family_rows),
        "existingLegacyPilots": len(pilots),
        "existingPriorityProfiles": len(priority_rows),
        "newIndividualProfiles": len(new_profiles),
        "newTechnicalRequirements": len(tasks),
        "existingPriorityRequirements": sum(
            len(row["technicalChecks"])
            for row in priority_rows
        ),
        "existingPilotTechnicalFactors": sum(
            len(factors)
            for factors in pilot_products.values()
        ),
        "sourcesNeedingFurtherAttention": len(source_exceptions),
        "verifiedNewEvidence": 0,
        "qualityTiersApproved": 0,
        "approvedForPublication": 0,
    }

    report = {
        "schemaVersion": 1,
        "status": "all_material_specific_criteria_defined_research_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "tierMappingsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "summary": summary,
        "families": family_coverage,
        "sourceExceptionsFromStage39": source_exceptions,
        "allMaterialProfiles": profiles,
    }

    research_queue = {
        "schemaVersion": 1,
        "status": "manual_research_tasks_not_verified",
        "publishedPricesChanged": False,
        "automaticPublicationEnabled": False,
        "summary": {
            "materials": len(new_profiles),
            "technicalTasks": len(tasks),
            "verifiedTasks": 0,
            "approvedForPublication": 0,
        },
        "tasks": tasks,
    }

    return report, research_queue


def make_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — индивидуальные критерии всех 41 материалов",
        "",
        "Это технический план проверки, а не утверждение качества.",
        "",
        f"- Материалов каталога: **{summary['catalogMaterials']}**.",
        f"- Материалов с определёнными индивидуальными критериями: **{summary['materialsWithIndividualCriteria']}**.",
        f"- Сохранённых пилотных профилей: **{summary['existingLegacyPilots']}**.",
        f"- Сохранённых приоритетных профилей: **{summary['existingPriorityProfiles']}**.",
        f"- Новых профилей: **{summary['newIndividualProfiles']}**.",
        f"- Новых технических требований: **{summary['newTechnicalRequirements']}**.",
        f"- Требующих дополнительного внимания источников этапа 39: **{summary['sourcesNeedingFurtherAttention']}**.",
        "- Новых независимо подтверждённых характеристик: **0**.",
        "- Утверждённых категорий качества: **0**.",
        "- Разрешений на публикацию: **0**.",
        "",
        "## Охват по техническим семействам",
        "",
        "| Семейство | Всего | Новых | Приоритетных | Старых пилотов |",
        "|---|---:|---:|---:|---:|",
    ]

    for group in report["families"]:
        lines.append(
            f"| {group['titleRu']} "
            f"| {group['catalogMaterials']} "
            f"| {group['newProfiles']} "
            f"| {group['priorityProfiles']} "
            f"| {group['legacyPilots']} |"
        )

    lines.extend(
        [
            "",
            "## Полная матрица материалов",
            "",
            "| Ключ каталога | Источник критериев | Пунктов | Проверено |",
            "|---|---|---:|---|",
        ]
    )

    for item in report["allMaterialProfiles"]:
        lines.append(
            f"| `{item['catalogMaterialKey']}` "
            f"| `{item['criteriaOrigin']}` "
            f"| {len(item['technicalCriteria'])} "
            "| Нет |"
        )

    lines.extend(
        [
            "",
            "## Источники, требующие внимания",
            "",
        ]
    )

    for item in report["sourceExceptionsFromStage39"]:
        lines.append(
            f"- `{item['catalogMaterialKey']}`: "
            f"`{item['sourceStatus']}`"
        )

    lines.extend(
        [
            "",
            "## Правила безопасности",
            "",
            "- Формирование критериев не является проверкой технических характеристик.",
            "- Для материала требуется точный товар, упаковка и применимый документ производителя.",
            "- Соответствие источника и доступность сайта не равны независимому подтверждению качества.",
            "- Бюджет, стандарт и премиум не назначаются по цене.",
            "- Действующие цены, нормы расхода и формулы COSTARO сохранены.",
            "- Автоматическая публикация остаётся выключенной.",
            "",
        ]
    )

    return "\n".join(lines)


def main():
    report, queue = build_report(
        load_json("material_family_criteria.json"),
        load_json("priority_material_criteria.json"),
        load_json("material_quality_first_review.json"),
        load_json("priority_source_batch_review.json"),
    )

    Path("complete_material_criteria.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    Path("remaining_material_research_tasks.json").write_text(
        json.dumps(queue, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    markdown = make_markdown(report)

    Path("complete_material_criteria_RU.md").write_text(
        markdown,
        encoding="utf-8",
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(markdown + "\n")

    print("=== COSTARO STAGE 40 ===")

    for key, value in report["summary"].items():
        print(f"{key}: {value}")

    print("No price, norm, calculation, tier or publication changes.")


if __name__ == "__main__":
    main()