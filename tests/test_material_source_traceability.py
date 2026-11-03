"""Network-free source traceability regression tests."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_material_source_traceability import audit, markdown, PINNED
from build_material_quality_dossiers import build as build_quality
from test_build_material_candidate_dossiers import research_fixture
from validate_app_catalog import load


NOW = datetime(2026, 11, 3, 16, tzinfo=timezone.utc)

PRICES = {
    "glet_b62_satroc_8kg": 191.0,
    "glet_satroc_8kg": 234.0,
    "euroton_lav_7kg": 325.0,
}


def fixture():
    sources = load(ROOT / "price_sources.json")
    tiers, technical = research_fixture()

    tiers["observationsFresh"] = True
    tiers["automaticPublicationEnabled"] = False
    tiers["approvedTierMappings"] = 0

    tier_by_id = {row["id"]: row for row in tiers["products"]}
    source_by_id = {row["id"]: row for row in sources["materials"]}

    observations = {
        "country": "MD",
        "currency": "MDL",
        "generatedAt": NOW.isoformat(),
        "materials": [],
    }

    for product_id, price in PRICES.items():
        config = source_by_id[product_id]
        rows = []

        for index, shop in enumerate(config["sources"]):
            rows.append({
                "store": shop["store"],
                "url": shop["url"],
                "productCode": shop["productCode"],
                "price": price,
                "status": "candidate",
                "extractionMethod": (
                    "product_structured_sku"
                    if index == 0
                    else "product_scoped_visible_text"
                ),
            })

        observations["materials"].append({
            "id": product_id,
            "observations": rows,
        })

        tier_by_id[product_id]["sourceObservations"] = [
            {
                "store": row["store"],
                "url": row["url"],
                "productCode": row["productCode"],
                "priceMDL": row["price"],
                "extractionMethod": row["extractionMethod"],
            }
            for row in rows
        ]

        tier_by_id[product_id]["candidateMedianMDL"] = price

    quality = build_quality(tiers, technical, now=NOW)

    return sources, observations, tiers, quality


class TraceabilityTests(unittest.TestCase):
    def test_three_mixed_candidates_remain_unapproved(self):
        report = audit(*fixture(), now=NOW)

        self.assertEqual(report["summary"]["productsReviewed"], 3)
        self.assertEqual(report["summary"]["twoCandidateQuotes"], 3)
        self.assertEqual(
            report["summary"]["fullyStructuredDualRetailSources"], 0
        )
        self.assertEqual(
            report["summary"]["manualIdentityReviewRequired"], 3
        )
        self.assertEqual(report["summary"]["publicationApproved"], 0)
        self.assertTrue(all(
            row["approvedForPublication"] is False
            for row in report["products"]
        ))

    def test_store_code_tampering_is_rejected(self):
        sources, observations, tiers, quality = fixture()

        observations["materials"][0]["observations"][1][
            "productCode"
        ] = "WRONG"

        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            audit(sources, observations, tiers, quality, now=NOW)

    def test_price_provenance_tampering_is_rejected(self):
        sources, observations, tiers, quality = fixture()

        observations["materials"][0]["observations"][0][
            "price"
        ] = 999.0

        with self.assertRaisesRegex(ValueError, "price provenance"):
            audit(sources, observations, tiers, quality, now=NOW)

    def test_quality_approval_is_not_accepted(self):
        sources, observations, tiers, quality = fixture()

        quality["products"][0]["qualityTierVerified"] = True

        with self.assertRaisesRegex(ValueError, "Unexpected approval"):
            audit(sources, observations, tiers, quality, now=NOW)

    def test_stale_observations_are_not_fresh(self):
        sources, observations, tiers, quality = fixture()

        observations["generatedAt"] = (
            NOW - timedelta(days=2)
        ).isoformat()

        report = audit(sources, observations, tiers, quality, now=NOW)

        self.assertTrue(all(
            row["retailObservationsFresh"] is False
            for row in report["products"]
        ))
        self.assertEqual(report["summary"]["publicationApproved"], 0)

    def test_unavailable_source_stays_held(self):
        sources, observations, tiers, quality = fixture()

        product_id = "glet_b62_satroc_8kg"

        raw = next(
            row for row in observations["materials"]
            if row["id"] == product_id
        )

        raw["observations"][1]["status"] = "unavailable"
        raw["observations"][1]["price"] = None

        tier = next(
            row for row in tiers["products"]
            if row["id"] == product_id
        )
        tier["status"] = "held"
        tier["sourceObservations"] = []
        tier["candidateMedianMDL"] = None

        dossier = next(
            row for row in quality["products"]
            if row["id"] == product_id
        )
        dossier["sourceResearchStatus"] = "held"
        dossier["shopEvidence"] = []
        dossier["researchPriceMedianMDL"] = None

        report = audit(sources, observations, tiers, quality, now=NOW)

        item = next(
            row for row in report["products"]
            if row["id"] == product_id
        )

        self.assertEqual(item["sourceScreeningStatus"], "held")
        self.assertFalse(item["approvedForPublication"])

    def test_inputs_unchanged(self):
        documents = fixture()
        before = deepcopy(documents)

        audit(*documents, now=NOW)

        self.assertEqual(documents, before)

    def test_markdown_explains_research_only(self):
        report = audit(*fixture(), now=NOW)
        rendered = markdown(report)

        self.assertIn("Исследовательский отчёт", rendered)
        self.assertIn("Публикация цен запрещена", rendered)
        self.assertIn("glet_satroc_8kg", rendered)


if __name__ == "__main__":
    unittest.main()