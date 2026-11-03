import copy
from datetime import date
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_manufacturer_evidence_leads import build as build_sources
from build_manufacturer_review_queue import build, render_markdown
from build_priority_material_criteria import build as build_priority
from test_priority_material_criteria import inputs


def fixture():
    catalog, family_report = inputs()
    priority = build_priority(catalog, family_report)
    source = build_sources(priority, today=date(2026, 11, 3))
    return priority, source


class ManufacturerReviewQueueTests(unittest.TestCase):

    def test_all_48_manual_tasks_are_created(self):
        priority, sources = fixture()
        report = build(priority, sources)

        summary = report["summary"]

        self.assertEqual(summary["priorityMaterials"], 8)
        self.assertEqual(summary["technicalRequirements"], 40)
        self.assertEqual(summary["manufacturerStatementsNeedingReview"], 23)
        self.assertEqual(summary["missingManufacturerStatements"], 17)
        self.assertEqual(summary["skuAndMoldovaAvailabilityTasks"], 8)
        self.assertEqual(summary["staleSourceRefreshTasks"], 0)
        self.assertEqual(summary["totalManualResearchTasks"], 48)

    def test_no_publication_or_quality_approval(self):
        priority, sources = fixture()
        report = build(priority, sources)

        self.assertEqual(report["summary"]["approvedQualityTiers"], 0)
        self.assertEqual(report["summary"]["approvedForPublication"], 0)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["tierMappingsChanged"])
        self.assertFalse(report["automaticTierAssignmentEnabled"])
        self.assertFalse(report["automaticPublicationEnabled"])

        for task in report["tasks"]:
            self.assertFalse(task["evidenceApproved"])
            self.assertFalse(task["qualityTierApproved"])
            self.assertFalse(task["priceChangeAllowed"])
            self.assertFalse(task["approvedForPublication"])

    def test_all_eight_materials_have_sku_tasks(self):
        priority, sources = fixture()
        report = build(priority, sources)

        sku_tasks = [
            item
            for item in report["tasks"]
            if item["taskType"] == "verify_exact_moldova_sku"
        ]

        self.assertEqual(len(sku_tasks), 8)
        self.assertEqual(
            {item["catalogMaterialKey"] for item in sku_tasks},
            {item["catalogMaterialKey"] for item in priority["materials"]},
        )

    def test_type_level_sources_have_high_identity_priority(self):
        priority, sources = fixture()
        report = build(priority, sources)

        for material_key in ("tilePerM2", "laminatePerM2"):
            task = next(
                row for row in report["tasks"]
                if row["catalogMaterialKey"] == material_key
                and row["taskType"] == "verify_exact_moldova_sku"
            )

            self.assertEqual(task["priority"], 1)

    def test_duplicate_source_criterion_is_rejected(self):
        priority, sources = fixture()
        altered = copy.deepcopy(sources)

        row = next(
            item for item in altered["candidates"]
            if item["catalogMaterialKey"] == "primer"
        )

        row["sourceClaims"].append(copy.deepcopy(row["sourceClaims"][0]))

        with self.assertRaises(ValueError):
            build(priority, altered)

    def test_invented_source_approval_is_rejected(self):
        priority, sources = fixture()
        sources["candidates"][0]["qualityTierApproved"] = True

        with self.assertRaises(ValueError):
            build(priority, sources)

    def test_missing_priority_profile_is_rejected(self):
        priority, sources = fixture()
        priority["materials"].pop()

        with self.assertRaises(ValueError):
            build(priority, sources)

    def test_changed_technical_evidence_is_rejected(self):
        priority, sources = fixture()
        priority["materials"][0]["technicalChecks"][0]["evidenceProvided"] = True

        with self.assertRaises(ValueError):
            build(priority, sources)

    def test_stale_sources_create_refresh_tasks(self):
        priority, _ = fixture()
        sources = build_sources(priority, today=date(2027, 3, 1))
        report = build(priority, sources)

        self.assertEqual(report["summary"]["staleSourceRefreshTasks"], 8)
        self.assertEqual(report["summary"]["totalManualResearchTasks"], 56)

    def test_inputs_are_not_modified(self):
        priority, sources = fixture()

        before_priority = copy.deepcopy(priority)
        before_sources = copy.deepcopy(sources)

        build(priority, sources)

        self.assertEqual(priority, before_priority)
        self.assertEqual(sources, before_sources)

    def test_russian_report_contains_research_queue(self):
        priority, sources = fixture()
        report = build(priority, sources)
        text = render_markdown(report)

        self.assertIn("48", text)
        self.assertIn("Недостающих характеристик", text)
        self.assertIn("Утверждённых категорий качества: **0**", text)


if __name__ == "__main__":
    unittest.main()