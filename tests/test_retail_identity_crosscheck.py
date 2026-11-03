import unittest
from datetime import date

from scripts.build_retail_identity_crosscheck import (
    EXPECTED_KEYS,
    RESEARCH_LEADS,
    build_report,
    render_markdown,
)


def fixtures():
    selected = {
        item["catalogMaterialKey"]: item
        for item in RESEARCH_LEADS
    }

    candidates = []

    for key in sorted(EXPECTED_KEYS):
        url = (
            selected[key]["manufacturerSourceUrl"]
            if key in selected
            else "https://example.org/technical-document"
        )
        candidates.append({
            "catalogMaterialKey": key,
            "sourceUrl": url,
        })

    leads = {
        "status": "manufacturer_research_only",
        "candidates": candidates,
    }

    queue = {
        "summary": {"totalManualResearchTasks": 48},
        "tasks": [
            {
                "taskType": "verify_exact_moldova_sku",
                "catalogMaterialKey": key,
            }
            for key in sorted(EXPECTED_KEYS)
        ],
    }

    return leads, queue


class RetailIdentityCrosscheckTests(unittest.TestCase):

    def test_two_matches_and_zero_approvals(self):
        leads, queue = fixtures()

        report = build_report(
            leads, queue, today=date(2026, 11, 3)
        )

        s = report["summary"]

        self.assertEqual(
            s["materialsWithPreliminaryNameAndPackMatch"], 2
        )
        self.assertEqual(s["retailerPageLeads"], 4)
        self.assertEqual(s["unresolvedSkuResearchTasks"], 8)
        self.assertEqual(
            s["manufacturerRetailSkuCrosswalksVerified"], 0
        )
        self.assertEqual(s["approvedForPublication"], 0)

        for item in report["materials"]:
            self.assertFalse(item["approvedForPublication"])
            self.assertFalse(
                item["manufacturerToRetailSkuVerified"]
            )
            self.assertFalse(item["qualityTierApproved"])

        self.assertFalse(report["automaticPublicationEnabled"])
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["consumptionNormsChanged"])

    def test_temperature_conflict_is_retained(self):
        leads, queue = fixtures()
        report = build_report(leads, queue)

        adhesive = next(
            item for item in report["materials"]
            if item["catalogMaterialKey"] == "tileAdhesive"
        )

        self.assertEqual(
            len(adhesive["technicalDiscrepancies"]), 1
        )

        conflict = adhesive["technicalDiscrepancies"][0]

        self.assertEqual(
            conflict["status"],
            "unresolved_conflicting_claims",
        )

        self.assertIn(
            "Характеристика НЕ подтверждена",
            render_markdown(report),
        )

    def test_changed_manufacturer_source_is_rejected(self):
        leads, queue = fixtures()
        leads["candidates"][0]["sourceUrl"] = (
            "https://example.org/changed-source"
        )

        with self.assertRaises(ValueError):
            build_report(leads, queue)

    def test_missing_sku_tasks_are_rejected(self):
        leads, queue = fixtures()
        queue["tasks"].pop()

        with self.assertRaises(ValueError):
            build_report(leads, queue)

    def test_old_snapshots_require_refresh(self):
        leads, queue = fixtures()

        report = build_report(
            leads, queue, today=date(2026, 12, 10)
        )

        self.assertTrue(report["snapshotNeedsRefresh"])
        self.assertFalse(
            report["sourcePagesFetchedDuringThisRun"]
        )


if __name__ == "__main__":
    unittest.main()
