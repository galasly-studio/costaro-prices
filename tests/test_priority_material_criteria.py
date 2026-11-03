import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_material_family_criteria import build as build_families
from build_priority_material_criteria import (
    PROFILES,
    PRINCIPLE,
    build,
    render_markdown,
)
from test_material_family_criteria import fixture


def inputs():
    catalog, quality_review = fixture()
    return catalog, build_families(catalog, quality_review)


class PriorityMaterialCriteriaTests(unittest.TestCase):

    def test_eight_priority_materials_and_forty_checks(self):
        catalog, family_report = inputs()
        report = build(catalog, family_report)
        summary = report["summary"]

        self.assertEqual(summary["catalogMaterials"], 41)
        self.assertEqual(summary["existingDetailedPilots"], 2)
        self.assertEqual(summary["newPriorityProfiles"], 8)
        self.assertEqual(
            summary["totalMaterialsWithIndividualCriteria"], 10
        )
        self.assertEqual(
            summary["materialsStillAwaitingIndividualCriteria"], 31
        )
        self.assertEqual(summary["technicalEvidenceRequirements"], 40)
        self.assertEqual(summary["verifiedEvidenceRequirements"], 0)

    def test_quality_and_publication_remain_unapproved(self):
        catalog, family_report = inputs()
        report = build(catalog, family_report)

        self.assertEqual(report["principle"], PRINCIPLE)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["tierMappingsChanged"])
        self.assertFalse(report["automaticTierAssignmentEnabled"])
        self.assertFalse(report["automaticPublicationEnabled"])

        for material in report["materials"]:
            self.assertEqual(material["qualityTier"], "unclassified")
            self.assertFalse(material["qualityTierApproved"])
            self.assertFalse(material["approvedForPublication"])

            for check in material["technicalChecks"]:
                self.assertIsNone(check["verifiedValue"])
                self.assertFalse(check["evidenceProvided"])
                self.assertFalse(check["evidenceReviewed"])

    def test_missing_priority_material_is_rejected(self):
        catalog, family_report = inputs()
        altered = copy.deepcopy(PROFILES)
        altered.pop("primer")

        with self.assertRaises(ValueError):
            build(catalog, family_report, altered)

    def test_duplicate_criterion_is_rejected(self):
        catalog, family_report = inputs()
        altered = copy.deepcopy(PROFILES)
        checks = altered["tileAdhesive"]["checks"]
        checks.append(checks[0])

        with self.assertRaises(ValueError):
            build(catalog, family_report, altered)

    def test_wrong_family_is_rejected(self):
        catalog, family_report = inputs()
        altered = copy.deepcopy(PROFILES)
        altered["tilePerM2"]["family"] = "electrical_components"

        with self.assertRaises(ValueError):
            build(catalog, family_report, altered)

    def test_existing_pilot_cannot_be_overwritten(self):
        catalog, family_report = inputs()
        altered = copy.deepcopy(PROFILES)
        altered.pop("primer")
        altered["finishPutty"] = copy.deepcopy(PROFILES["primer"])

        with self.assertRaises(ValueError):
            build(catalog, family_report, altered)

    def test_price_cannot_change_quality_requirements(self):
        catalog, family_report = inputs()
        original = build(catalog, family_report)

        altered_catalog = copy.deepcopy(catalog)
        altered_catalog["materialPrices"]["tileAdhesive"] = {
            "unverifiedPrice": 999999
        }

        self.assertEqual(
            original,
            build(altered_catalog, family_report),
        )

    def test_unsafe_source_report_is_rejected(self):
        catalog, family_report = inputs()
        family_report["automaticPublicationEnabled"] = True

        with self.assertRaises(ValueError):
            build(catalog, family_report)

    def test_unapproved_source_materials_are_required(self):
        catalog, family_report = inputs()
        family_report["materialCoverage"][0]["qualityTierApproved"] = True

        with self.assertRaises(ValueError):
            build(catalog, family_report)

    def test_inputs_are_not_modified(self):
        catalog, family_report = inputs()
        before_catalog = copy.deepcopy(catalog)
        before_report = copy.deepcopy(family_report)

        build(catalog, family_report)

        self.assertEqual(catalog, before_catalog)
        self.assertEqual(family_report, before_report)

    def test_russian_report_contains_all_materials(self):
        catalog, family_report = inputs()
        report = build(catalog, family_report)
        markdown = render_markdown(report)

        for profile in PROFILES.values():
            self.assertIn(profile["nameRu"], markdown)

        self.assertIn("Утверждённых категорий качества: 0", markdown)
        self.assertIn("31", markdown)


if __name__ == "__main__":
    unittest.main()