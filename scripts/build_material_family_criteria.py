import json
from pathlib import Path


# Research policy only. No price, norm, Flutter or tier publication writes.
FAMILIES = {
    "surface_compounds": {
        "titleRu": "Штукатурки, шпаклёвки и строительные смеси",
        "keys": (
            "gypsumPlaster cementPlaster decorativePlaster "
            "startPutty finishPutty floorScreedMix selfLevelingFloorMix"
        ).split(),
        "criteriaRu": [
            "Назначение, основание и допустимые условия применения.",
            "Допустимая толщина слоя и технические ограничения.",
            "Расход при сопоставимых условиях и количестве слоёв.",
            "Прочность, адгезия или свойства поверхности там, где применимо.",
            "Совместимость с последующими отделочными слоями."
        ],
        "comparisonRu": (
            "Сравнивать товары одного назначения и технологии. "
            "Штукатурка, шпаклёвка и наливной пол не являются взаимозаменяемыми."
        ),
        "referenceExampleRu": (
            "Для подходящих видов шпаклёвок можно исследовать применимость "
            "EN 16566. Стандарт не назначает категорию COSTARO автоматически."
        )
    },

    "chemical_systems": {
        "titleRu": "Грунтовки, клеи, затирки и гидроизоляция",
        "keys": (
            "primer tileAdhesive grout wallpaperGlue floorWaterproofing"
        ).split(),
        "criteriaRu": [
            "Назначение и совместимость с основанием.",
            "Условия применения, включая влажные помещения.",
            "Расход по документации производителя.",
            "Адгезия, водостойкость или другие профильные характеристики.",
            "Совместимость материалов в одной технологической системе."
        ],
        "comparisonRu": (
            "Не сравнивать универсальную грунтовку с клеем или гидроизоляцией. "
            "Для каждого назначения нужны отдельные сопоставимые показатели."
        ),
        "referenceExampleRu": (
            "Для соответствующих плиточных клеёв исследовать классификацию "
            "по EN 12004-1; она не распространяется автоматически на всю группу."
        )
    },

    "wall_finishes": {
        "titleRu": "Краски и обои",
        "keys": "interiorPaint wallpaper".split(),
        "criteriaRu": [
            "Предназначение для сухих или влажных помещений.",
            "Стойкость к очистке и истиранию, когда применимо.",
            "Укрывистость и расход для красок.",
            "Материал, плотность и свойства покрытия для обоев.",
            "Сопоставимость назначения и условий эксплуатации."
        ],
        "comparisonRu": (
            "Краску сравнивать с краской, обои — с обоями. "
            "Высокая розничная цена сама по себе не доказывает качество."
        ),
        "referenceExampleRu": (
            "Для соответствующих интерьерных красок исследовать показатели "
            "EN 13300, включая стойкость к влажному истиранию."
        )
    },

    "floor_coverings": {
        "titleRu": "Напольные покрытия",
        "keys": (
            "tilePerM2 laminatePerM2 laminateUnderlayPerM2 "
            "linoleumPerM2 vinylPerM2"
        ).split(),
        "criteriaRu": [
            "Назначение помещения и предполагаемая эксплуатационная нагрузка.",
            "Стойкость к износу и влаге, когда применимо.",
            "Тип покрытия, устройство и способ монтажа.",
            "Размеры, толщина и совместимость с основанием.",
            "Требования к подложке и соединениям, когда применимо."
        ],
        "comparisonRu": (
            "Плитка, ламинат, линолеум, винил и подложка оцениваются "
            "по разным профильным характеристикам."
        ),
        "referenceExampleRu": (
            "Для соответствующей керамической плитки исследовать EN 14411. "
            "Не применять его к ламинату или винилу."
        )
    },

    "electrical_components": {
        "titleRu": "Электротехнические материалы",
        "keys": (
            "electricalLightingCablePerM "
            "electricalLightingConnectorPerPoint "
            "electricalSocketCablePerM "
            "electricalSocketPerPiece "
            "electricalSubboxPerPiece "
            "electricalSwitchPerPiece"
        ).split(),
        "criteriaRu": [
            "Назначение и условия электрической установки.",
            "Номинальные параметры и ограничения применения.",
            "Для кабеля — материал и сечение проводников.",
            "Для устройств — электрические параметры и совместимость.",
            "Подтверждённые технические и защитные характеристики."
        ],
        "comparisonRu": (
            "Кабель, розетку, выключатель, соединитель и подрозетник "
            "сравнивать только с изделиями соответствующего типа."
        ),
        "referenceExampleRu": (
            "Для соответствующих кабельных проводников исследовать "
            "IEC 60228. Это не единый стандарт для всех электротоваров."
        )
    },

    "drywall_ceiling_system": {
        "titleRu": "Система гипсокартонного потолка",
        "keys": (
            "gypsumBoardCeiling ceilingCdProfile "
            "ceilingUdProfile ceilingJointTape"
        ).split(),
        "criteriaRu": [
            "Назначение компонента внутри потолочной системы.",
            "Размеры, толщина и технические свойства материала.",
            "Совместимость с другими элементами каркаса и отделки.",
            "Влагостойкость или огнестойкость там, где это требуется.",
            "Наличие подтверждённой документации производителя."
        ],
        "comparisonRu": (
            "Лист, профиль и армирующая лента оцениваются отдельно. "
            "Совместимость системы обязательна для дальнейшего анализа."
        ),
        "referenceExampleRu": (
            "Применимые стандарты и испытания выбирать отдельно "
            "для листа, металлического профиля и ленты."
        )
    },

    "fixings_hardware": {
        "titleRu": "Крепёж и соединительные элементы",
        "keys": (
            "ceilingBaseAnchorPerPiece "
            "ceilingCrossConnectorPerPiece "
            "ceilingDirectHangerPerPiece "
            "ceilingDrywallScrews "
            "ceilingExtensionConnectorPerPiece "
            "ceilingFrameFastenersPerM2 "
            "ceilingMetalScrews "
            "ceilingUdFastenerPerPiece"
        ).split(),
        "criteriaRu": [
            "Точное назначение крепёжного или соединительного элемента.",
            "Размеры, материал и защитное покрытие.",
            "Совместимость с основанием и элементами каркаса.",
            "Несущие характеристики там, где применимо.",
            "Подтверждённые условия монтажа и эксплуатации."
        ],
        "comparisonRu": (
            "Не заменять нагрузочный крепёж другим видом крепления "
            "по принципу меньшей цены или внешнего сходства."
        ),
        "referenceExampleRu": (
            "Подтверждающие документы и испытания подбирать по типу "
            "крепежа и предусмотренной нагрузке."
        )
    },

    "skirting_accessories": {
        "titleRu": "Плинтусы и комплектующие",
        "keys": (
            "mdfSkirtingPiece pvcSkirtingPiece "
            "woodSkirtingPiece skirtingAccessoryPerPiece"
        ).split(),
        "criteriaRu": [
            "Материал и назначение плинтуса или аксессуара.",
            "Габариты, длина и конструкция.",
            "Устойчивость к влаге и механическому воздействию.",
            "Совместимость аксессуаров с конкретным типом плинтуса.",
            "Подтверждённые условия установки и ухода."
        ],
        "comparisonRu": (
            "МДФ, ПВХ, дерево и комплектующие имеют разные свойства. "
            "Их нельзя ранжировать только по розничной стоимости."
        ),
        "referenceExampleRu": (
            "Доказательства оценивать по материалу, месту применения "
            "и совместимости комплектующих."
        )
    }
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


def build(catalog, quality_review, families=None):
    groups = FAMILIES if families is None else families

    require(
        catalog.get("schemaVersion") == 1
        and catalog.get("country") == "MD"
        and catalog.get("currency") == "MDL",
        "Unexpected Moldova catalog schema",
    )
    require(
        catalog.get("status") == "draft"
        and catalog.get("automaticUpdatesEnabled") is False,
        "Catalog publication safety state changed",
    )

    material_prices = catalog.get("materialPrices")
    require(
        isinstance(material_prices, dict)
        and len(material_prices) == 41,
        "Expected exactly 41 catalog material keys",
    )
    catalog_keys = set(material_prices)

    require(
        isinstance(groups, dict) and len(groups) == 8,
        "Expected exactly eight technical families",
    )

    membership = {}
    family_rows = []

    for family_id, family in groups.items():
        keys = family.get("keys")
        criteria = family.get("criteriaRu")

        require(
            isinstance(keys, (list, tuple)) and len(keys) > 0,
            f"Empty family: {family_id}",
        )
        require(
            isinstance(criteria, (list, tuple)) and len(criteria) >= 3,
            f"Missing technical criteria: {family_id}",
        )
        require(
            isinstance(family.get("titleRu"), str)
            and bool(family["titleRu"].strip()),
            f"Missing family title: {family_id}",
        )

        for key in keys:
            require(
                key not in membership,
                f"Material belongs to multiple families: {key}",
            )
            require(
                key in catalog_keys,
                f"Unknown catalog material in family {family_id}: {key}",
            )
            membership[key] = family_id

        family_rows.append({
            "familyId": family_id,
            "titleRu": family["titleRu"],
            "materialCount": len(keys),
            "catalogMaterialKeys": list(keys),
            "technicalCriteriaRu": list(criteria),
            "comparabilityRuleRu": family["comparisonRu"],
            "referenceExampleRu": family["referenceExampleRu"],
            "individualProductQualityApproved": False,
            "automaticTierAssignmentAllowed": False,
        })

    require(
        set(membership) == catalog_keys,
        "Some catalog materials have no technical family: "
        + ", ".join(sorted(catalog_keys - set(membership))),
    )

    require(
        quality_review.get("schemaVersion") == 1
        and quality_review.get("policyVersion") == 1
        and quality_review.get("status") == "quality_first_research_only",
        "Unexpected Stage 31 quality-first report",
    )

    require(
        quality_review.get("principle") == PRINCIPLE,
        "Quality-first principle changed",
    )

    for flag in (
        "publishedPricesChanged",
        "flutterCalculationsChanged",
        "tierMappingsChanged",
    ):
        require(
            quality_review.get(flag) is False,
            f"Unexpected source safety flag: {flag}",
        )

    source_summary = quality_review.get("summary", {})

    require(
        source_summary.get("catalogMaterialsCoveredByUniversalRule") == 41,
        "Stage 31 did not cover 41 catalog materials",
    )
    require(
        source_summary.get("qualityTiersApproved") == 0
        and source_summary.get("approvedForPublication") == 0,
        "Unexpected quality or publication approval",
    )

    source_materials = quality_review.get("materials")

    require(
        isinstance(source_materials, list)
        and len(source_materials) == 41,
        "Unexpected Stage 31 material count",
    )

    source_by_key = {}

    for item in source_materials:
        require(
            isinstance(item, dict),
            "Invalid Stage 31 material row",
        )

        key = item.get("catalogMaterialKey")

        require(
            key not in source_by_key,
            f"Duplicate Stage 31 material: {key}",
        )
        require(
            item.get("universalQualityFirstRulesApply") is True
            and item.get("automaticallyApproved") is False,
            f"Unsafe Stage 31 material: {key}",
        )
        require(
            item.get("detailedCriteriaStatus")
            in ("pilot_defined", "material_specific_criteria_pending"),
            f"Unexpected detailed criteria status: {key}",
        )

        source_by_key[key] = item

    require(
        set(source_by_key) == catalog_keys,
        "Stage 31 material list differs from current catalog",
    )

    pilots = sum(
        item["detailedCriteriaStatus"] == "pilot_defined"
        for item in source_materials
    )
    pending = sum(
        item["detailedCriteriaStatus"] == "material_specific_criteria_pending"
        for item in source_materials
    )

    require(
        pilots == source_summary.get("materialGroupsWithDetailedPilotCriteria")
        and pending == source_summary.get("materialGroupsAwaitingDetailedCriteria")
        and pilots + pending == 41,
        "Stage 31 detailed criteria counts disagree",
    )

    products = quality_review.get("products")

    require(
        isinstance(products, list)
        and len(products) == source_summary.get("pilotProductsReviewed"),
        "Unexpected Stage 31 product count",
    )

    for product in products:
        require(
            product.get("qualityTierApproved") is False
            and product.get("priceCanDetermineQualityTier") is False
            and product.get("approvedForPublication") is False,
            "Source contains an unexpected product approval",
        )

    coverage = []

    for key in sorted(catalog_keys):
        family_id = membership[key]
        coverage.append({
            "catalogMaterialKey": key,
            "technicalFamilyId": family_id,
            "technicalFamilyTitleRu": groups[family_id]["titleRu"],
            "individualCriteriaStatus": (
                source_by_key[key]["detailedCriteriaStatus"]
            ),
            "qualityTierApproved": False,
            "approvedForPublication": False,
        })

    return {
        "schemaVersion": 1,
        "status": "material_family_criteria_research_only",
        "policyVersion": 1,
        "sourceReviewGeneratedAt": quality_review.get("generatedAt"),
        "principle": dict(PRINCIPLE),
        "summary": {
            "catalogMaterials": 41,
            "technicalFamilies": 8,
            "materialsAssignedExactlyOnce": 41,
            "materialsUnassigned": 0,
            "materialsMultiplyAssigned": 0,
            "materialsWithExistingDetailedPilotCriteria": pilots,
            "materialsAwaitingIndividualDetailedCriteria": pending,
            "pilotProductsReviewed": len(products),
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "families": family_rows,
        "materialCoverage": coverage,
        "familyCriteriaAreNotIndividualProductApproval": True,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
        "automaticPublicationEnabled": False,
    }


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — технические семейства материалов",
        "",
        "**Статус: исследование. Не является утверждением качества или цен.**",
        "",
        "## Результат проверки",
        "",
        f"- Материалов каталога: **{summary['catalogMaterials']}**",
        f"- Технических семейств: **{summary['technicalFamilies']}**",
        (
            "- Материалов, отнесённых ровно к одному семейству: "
            f"**{summary['materialsAssignedExactlyOnce']}**"
        ),
        f"- Материалов без семейства: **{summary['materialsUnassigned']}**",
        (
            "- Материалов с несколькими семействами: "
            f"**{summary['materialsMultiplyAssigned']}**"
        ),
        (
            "- Материалов с подробными пилотными критериями: "
            f"**{summary['materialsWithExistingDetailedPilotCriteria']}**"
        ),
        (
            "- Материалов, ожидающих индивидуальных критериев: "
            f"**{summary['materialsAwaitingIndividualDetailedCriteria']}**"
        ),
        "- Утверждённых категорий качества: **0**",
        "- Разрешений на публикацию: **0**",
        "",
        "## Критерии по техническому назначению",
        "",
    ]

    for family in report["families"]:
        lines.extend([
            f"### {family['titleRu']}",
            "",
            f"Материалов: **{family['materialCount']}**.",
            "",
            "Ключи: " + ", ".join(
                f"`{key}`" for key in family["catalogMaterialKeys"]
            ),
            "",
        ])

        for criterion in family["technicalCriteriaRu"]:
            lines.append(f"- {criterion}")

        lines.extend([
            "",
            f"**Сопоставимость:** {family['comparabilityRuleRu']}",
            "",
            f"**Технический ориентир:** {family['referenceExampleRu']}",
            "",
        ])

    lines.extend([
        "## Правило COSTARO",
        "",
        "1. Категорию «Бюджет / Стандарт / Премиум» определяет "
        "подтверждённое качество и сопоставимые технические характеристики.",
        "2. Стоимость определяет отдельно подтверждённая актуальная "
        "рыночная цена подходящего товара.",
        "3. Цена сама по себе никогда не определяет категорию качества.",
        "4. Пока индивидуальные характеристики не проверены, "
        "категория товара остаётся неутверждённой.",
        "",
        "**Действующие цены, нормы расхода, формулы Flutter "
        "и соответствия ценовым категориям не изменены.**",
        "",
    ])

    return "\n".join(lines)


def main():
    catalog = json.loads(
        Path("prices.json").read_text(encoding="utf-8")
    )
    quality_review = json.loads(
        Path("material_quality_first_review.json").read_text(
            encoding="utf-8"
        )
    )

    report = build(catalog, quality_review)

    Path("material_family_criteria.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    Path("material_family_criteria_RU.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )

    print("COSTARO STAGE 32: OK")
    print("Technical families: 8")
    print("Catalog materials assigned exactly once: 41/41")
    print("Missing or duplicate assignments: 0")
    print("Quality tiers approved: 0")
    print("Price and Flutter calculation changes: 0")


if __name__ == "__main__":
    main()