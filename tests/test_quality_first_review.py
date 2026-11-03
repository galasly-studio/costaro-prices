"""Network-free tests of COSTARO Stage 31 quality-first policy."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_quality_first_review import (
    build,
    markdown,
    DETAILED_CRITERIA,
)
from audit_material_source_traceability import audit
from test_material_source_traceability import fixture, NOW
from validate_app_catalog import load


def make_documents():
    sources, observations, tiers, quality = fixture()

    traceability = audit(
        sources, observations, tiers, quality, now=NOW
    )

    catalog = load(ROOT / "prices.json")

    return catalog, quality, traceability


class QualityFirstTests(unittest.TestCase):
    def test_all_materials_get_universal_rule(self):
        report = build(*make_documents(), now=NOW)

        self.assertEqual(
            report["summary"]["catalogMaterialsCoveredByUniversalRule"],
            41,
        )

        self.assertEqual(
            report["summary"]["materialGroupsWithDetailedPilotCriteria"],
            2,
        )

        self.assertEqual(
            report["summary"]["materialGroupsAwaitingDetailedCriteria"],
            39,
        )

        self.assertTrue(all(
            row["universalQualityFirstRulesApply"]
            for row in report["materials"]
        ))

    def test_no_quality_tier_or_publication_approved(self):
        report = build(*make_documents(), now=NOW)

        self.assertEqual(report["summary"]["pilotProductsReviewed"], 3)
        self.assertEqual(report["summary"]["qualityTiersApproved"], 0)
        self.assertEqual(report["summary"]["approvedForPublication"], 0)

        self.assertTrue(all(
            row["qualityTierApproved"] is False
            and row["approvedForPublication"] is False
            for row in report["products"]
        ))

    def test_price_alone_never_sets_quality(self):
        catalog, quality, traceability = make_documents()

        first = build(catalog, quality, traceability, now=NOW)

        quality["products"][0]["researchPriceMedianMDL"] = 1000000
        traceability["products"][0]["researchMedianMDL"] = 1000000

        second = build(catalog, quality, traceability, now=NOW)

        self.assertEqual(
            first["summary"]["qualityTiersApproved"],
            second["summary"]["qualityTiersApproved"],
        )

        self.assertEqual(
            first["products"],
            second["products"],
        )

    def test_unexpected_quality_approval_rejected(self):
        catalog, quality, traceability = make_documents()

        quality["products"][0]["qualityTierVerified"] = True

        with self.assertRaisesRegex(ValueError, "approval"):
            build(catalog, quality, traceability, now=NOW)

    def test_catalog_prices_not_modified(self):
        documents = make_documents()
        snapshot = deepcopy(documents)

        build(*documents, now=NOW)

        self.assertEqual(documents, snapshot)

    def test_missing_product_rejected(self):
        catalog, quality, traceability = make_documents()

        quality["products"].pop()

        with self.assertRaisesRegex(ValueError, "IDs differ"):
            build(catalog, quality, traceability, now=NOW)

    def test_source_hold_does_not_approve_quality(self):
        catalog, quality, traceability = make_documents()

        traceability["products"][0][
            "sourceScreeningStatus"
        ] = "held"

        report = build(catalog, quality, traceability, now=NOW)

        self.assertEqual(report["summary"]["qualityTiersApproved"], 0)

    def test_criteria_reference_valid_catalog_materials(self):
        catalog, quality, traceability = make_documents()

        self.assertIn("finishPutty", DETAILED_CRITERIA)
        self.assertIn("interiorPaint", DETAILED_CRITERIA)

        del catalog["materialPrices"]["finishPutty"]

        with self.assertRaisesRegex(ValueError, "unknown materials"):
            build(catalog, quality, traceability, now=NOW)

    def test_report_states_quality_first_principle(self):
        report = build(*make_documents(), now=NOW)

        self.assertTrue(
            report["principle"]["qualityDeterminesTier"]
        )
        self.assertTrue(
            report["principle"]["verifiedMarketPriceDeterminesCost"]
        )
        self.assertTrue(
            report["principle"]["priceAloneMayNeverDetermineTier"]
        )

        content = markdown(report)

        self.assertIn("Качество определяет категорию", content)
        self.assertIn("не утверждено", content)
        self.assertIn("EN 13300", content)
        self.assertIn("EN 16566", content)


if __name__ == "__main__":
    unittest.main()