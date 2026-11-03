import unittest
from datetime import date

from scripts.build_product_provenance_review import (
    build_report,
    render_markdown,
)


def fixtures():
    crosscheck = {
        "status": "manual_retail_identity_crosscheck_only",
        "summary": {
            "materialsWithPreliminaryNameAndPackMatch": 2,
            "unresolvedSkuResearchTasks": 8,
        },
        "materials": [
            {
                "catalogMaterialKey": "tileAdhesive",
                "approvedForPublication": False,
            },
            {
                "catalogMaterialKey": "cementPlaster",
                "approvedForPublication": False,
            },
        ],
    }

    queue = {
        "summary": {
            "totalManualResearchTasks": 48,
        },
    }

    return crosscheck, queue


class ProductProvenanceTests(unittest.TestCase):

    def test_research_documented_without_approvals(self):
        crosscheck, queue = fixtures()
        report = build_report(crosscheck, queue)

        self.assertEqual(
            report["summary"][
                "manufacturerArticleCrossReferencesDocumented"
            ],
            1,
        )
        self.assertEqual(report["summary"]["closedSkuTasks"], 0)
        self.assertEqual(report["summary"]["unresolvedSkuTasks"], 8)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["consumptionNormsChanged"])
        self.assertFalse(report["tierMappingsChanged"])
        self.assertFalse(report["automaticPublicationEnabled"])

        for material in report["materials"]:
            self.assertFalse(material["approvedForPublication"])
            self.assertFalse(material["qualityTierApproved"])
            self.assertFalse(
                material["exactCurrentRetailPackageVerified"]
            )

    def test_temperature_conflict_has_three_sources(self):
        crosscheck, queue = fixtures()
        report = build_report(crosscheck, queue)

        adhesive = next(
            m for m in report["materials"]
            if m["catalogMaterialKey"] == "tileAdhesive"
        )

        values = {
            item["claimC"]
            for item in adhesive["temperatureClaimHistory"]
        }

        self.assertEqual(values, {70, 250, 300})
        self.assertTrue(adhesive["technicalConflictUnresolved"])

    def test_retail_ean_is_not_manufacturer_approved(self):
        crosscheck, queue = fixtures()
        report = build_report(crosscheck, queue)

        for item in report["materials"]:
            if item["catalogMaterialKey"] == "tileAdhesive":
                self.assertFalse(
                    item["retailerArticleCrossReference"][
                        "manufacturerConfirmedEAN"
                    ]
                )
            else:
                self.assertFalse(
                    item["crossBorderEANResearch"][
                        "manufacturerConfirmedEAN"
                    ]
                )

    def test_old_snapshot_requires_refresh(self):
        crosscheck, queue = fixtures()

        report = build_report(
            crosscheck, queue, today=date(2026, 12, 10)
        )

        self.assertTrue(report["sourceNeedsRefresh"])
        self.assertFalse(
            report["sourcePagesFetchedDuringThisRun"]
        )

    def test_changed_stage36_baseline_is_rejected(self):
        crosscheck, queue = fixtures()
        crosscheck["summary"]["unresolvedSkuResearchTasks"] = 7

        with self.assertRaises(ValueError):
            build_report(crosscheck, queue)

    def test_markdown_contains_protective_conclusion(self):
        crosscheck, queue = fixtures()
        report = build_report(crosscheck, queue)
        text = render_markdown(report)

        self.assertIn("510027", text)
        self.assertIn("5945752000371", text)
        self.assertIn("не подтверждено", text)


if __name__ == "__main__":
    unittest.main()
