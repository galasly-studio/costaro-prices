import copy
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_material_family_criteria import (
    FAMILIES,
    PRINCIPLE,
    build,
    render_markdown,
)


def fixture():
    catalog = json.loads(
        (ROOT / "prices.json").read_text(encoding="utf-8")
    )

    keys = sorted(catalog["materialPrices"])

    materials = []

    for key in keys:
        materials.append({
            "catalogMaterialKey": key,
            "universalQualityFirstRulesApply": True,
            "detailedCriteriaStatus": (
                "pilot_defined"
                if key in ("finishPutty", "interiorPaint")
                else "material_specific_criteria_pending"
            ),
            "automaticallyApproved": False,
        })

    review = {
        "schemaVersion": 1,
        "policyVersion": 1,
        "status": "quality_first_research_only",
        "principle": dict(PRINCIPLE),
        "summary": {
            "catalogMaterialsCoveredByUniversalRule": 41,
            "materialGroupsWithDetailedPilotCriteria": 2,
            "materialGroupsAwaitingDetailedCriteria": 39,
            "pilotProductsReviewed": 3,
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "materials": materials,
        "products": [
            {
                "qualityTierApproved": False,
                "priceCanDetermineQualityTier": False,
                "approvedForPublication": False,
            }
            for _ in range(3)
        ],
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
    }

    return catalog, review


class MaterialFamilyCriteriaTests(unittest.TestCase):

    def test_all_41_materials_belong_to_exactly_one_of_eight_families(self):
        catalog, review = fixture()
        report = build(catalog, review)

        self.assertEqual(report["summary"]["catalogMaterials"], 41)
        self.assertEqual(report["summary"]["technicalFamilies"], 8)
        self.assertEqual(
            report["summary"]["materialsAssignedExactlyOnce"], 41
        )
        self.assertEqual(report["summary"]["materialsUnassigned"], 0)
        self.assertEqual(
            report["summary"]["materialsMultiplyAssigned"], 0
        )
        self.assertEqual(len(report["materialCoverage"]), 41)
        self.assertEqual(
            sum(item["materialCount"] for item in report["families"]),
            41,
        )

    def test_existing_two_pilots_remain_unapproved(self):
        catalog, review = fixture()
        report = build(catalog, review)

        self.assertEqual(
            report["summary"]["materialsWithExistingDetailedPilotCriteria"],
            2,
        )
        self.assertEqual(
            report["summary"]["materialsAwaitingIndividualDetailedCriteria"],
            39,
        )
        self.assertEqual(report["summary"]["qualityTiersApproved"], 0)
        self.assertEqual(report["summary"]["approvedForPublication"], 0)

        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["tierMappingsChanged"])
        self.assertFalse(report["automaticPublicationEnabled"])

        self.assertTrue(all(
            not item["qualityTierApproved"]
            and not item["approvedForPublication"]
            for item in report["materialCoverage"]
        ))

    def test_duplicate_family_assignment_is_rejected(self):
        catalog, review = fixture()
        families = copy.deepcopy(FAMILIES)
        families["wall_finishes"]["keys"].append("finishPutty")

        with self.assertRaises(ValueError):
            build(catalog, review, families=families)

    def test_unknown_material_is_rejected(self):
        catalog, review = fixture()
        families = copy.deepcopy(FAMILIES)
        families["wall_finishes"]["keys"].append("unknownMaterial")

        with self.assertRaises(ValueError):
            build(catalog, review, families=families)

    def test_missing_material_is_rejected(self):
        catalog, review = fixture()
        families = copy.deepcopy(FAMILIES)
        families["wall_finishes"]["keys"].remove("wallpaper")

        with self.assertRaises(ValueError):
            build(catalog, review, families=families)

    def test_price_change_cannot_change_family_or_quality(self):
        catalog, review = fixture()

        first = build(catalog, review)

        altered_catalog = copy.deepcopy(catalog)
        altered_catalog["materialPrices"]["interiorPaint"] = {
            "unverifiedPrice": 999999
        }

        second = build(altered_catalog, review)

        self.assertEqual(first, second)

    def test_inputs_are_not_modified(self):
        catalog, review = fixture()
        catalog_before = copy.deepcopy(catalog)
        review_before = copy.deepcopy(review)

        build(catalog, review)

        self.assertEqual(catalog, catalog_before)
        self.assertEqual(review, review_before)

    def test_changed_quality_principle_is_rejected(self):
        catalog, review = fixture()
        review["principle"]["priceAloneMayNeverDetermineTier"] = False

        with self.assertRaises(ValueError):
            build(catalog, review)

    def test_unexpected_tier_approval_is_rejected(self):
        catalog, review = fixture()
        review["products"][0]["qualityTierApproved"] = True

        with self.assertRaises(ValueError):
            build(catalog, review)

    def test_published_catalog_is_rejected(self):
        catalog, review = fixture()
        catalog["status"] = "published"
        catalog["automaticUpdatesEnabled"] = True

        with self.assertRaises(ValueError):
            build(catalog, review)

    def test_stage31_coverage_mismatch_is_rejected(self):
        catalog, review = fixture()
        review["materials"].pop()

        with self.assertRaises(ValueError):
            build(catalog, review)

    def test_russian_report_contains_all_families(self):
        catalog, review = fixture()
        report = build(catalog, review)
        text = render_markdown(report)

        for family in FAMILIES.values():
            self.assertIn(family["titleRu"], text)

        self.assertIn("Утверждённых категорий качества: **0**", text)
        self.assertIn("41", text)


if __name__ == "__main__":
    unittest.main()