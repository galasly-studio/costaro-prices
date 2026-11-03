"""Network-free Stage 27 material research and publication safety tests."""

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_consumption_alignment import audit
from build_material_candidate_dossiers import build, markdown
from plan_verified_material_updates import plan
from prepare_verified_catalog_release import prepare
from validate_app_catalog import load

NOW = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)

NEEDS_SKU_REVIEW = {
    "glet_b62_satroc_8kg",
    "glet_satroc_8kg",
    "euroton_lav_7kg",
    "sansiro_7kg",
}


def research_fixture():
    technical = audit(
        load(ROOT / "prices.json"),
        load(ROOT / "app_embedded_baseline.json"),
        load(ROOT / "price_sources.json"),
        load(ROOT / "material_consumption_evidence.json"),
    )
    tiers = {
        "schemaVersion": 1,
        "status": "human_review_only",
        "pricesChanged": False,
        "products": [],
    }
    for index, row in enumerate(technical["products"]):
        tiers["products"].append({
            "id": row["id"],
            "catalogMaterialKey": row["catalogMaterialKey"],
            "tierHintForHumanReview": row["tierHintForHumanReview"],
            "status": "manual_review_candidate",
            "reason": None,
            "candidateMedianMDL": 180 + index * 20,
            "exactPackMatchingTiers": ["budget", "standard", "premium"],
            "sourceObservations": [],
            "skuAndMethodReviewRequired": row["id"] in NEEDS_SKU_REVIEW,
            "tierQualityReviewed": False,
            "approvedForPublication": False,
        })
    return tiers, technical


def guarded_fixture(material, weight, prices):
    catalog = load(ROOT / "prices.json")
    baseline = load(ROOT / "app_embedded_baseline.json")
    catalog["status"] = "published"
    catalog["automaticUpdatesEnabled"] = True

    stores = [
        {
            "store": "Independent A",
            "url": "https://independent-a.md/product",
            "productCode": "sku-a",
        },
        {
            "store": "Independent B",
            "url": "https://independent-b.md/product",
            "productCode": "sku-b",
        },
    ]

    source = {
        "id": "stage27_synthetic_product",
        "catalogMaterialKey": material,
        "priceTier": "standard",
        "unit": "bucket",
        "packageWeightKg": weight,
        "sources": stores,
    }

    sources = {
        "country": "MD",
        "currency": "MDL",
        "materials": [source],
    }
    observations = {
        "country": "MD",
        "currency": "MDL",
        "generatedAt": NOW.isoformat(),
        "materials": [{
            "id": source["id"],
            "observations": [
                {
                    **store,
                    "status": "candidate",
                    "extractionMethod": "product_microdata",
                    "price": price,
                }
                for store, price in zip(stores, prices)
            ],
        }],
    }
    policy = {
        "schemaVersion": 1,
        "enabled": True,
        "automaticPublicationApproved": True,
        "approvedMappings": [{
            "observationId": source["id"],
            "catalogMaterialKey": material,
            "tier": "standard",
        }],
    }
    return catalog, baseline, sources, observations, policy


class MaterialDossierTests(unittest.TestCase):
    def test_six_dossiers_and_expected_priorities(self):
        tiers, technical = research_fixture()
        result = build(tiers, technical)
        self.assertEqual(result["summary"]["reviewed"], 6)
        self.assertEqual(result["summary"]["priorityP1"], 3)
        self.assertEqual(result["summary"]["priorityP2"], 3)
        self.assertEqual(result["summary"]["approvedForPublication"], 0)
        self.assertTrue(all(
            not row["approvedForPublication"] for row in result["products"]
        ))
        self.assertIn("Только", markdown(result).replace("Исследование", "Только"))

    def test_technical_holds_remain_even_with_shop_quotes(self):
        tiers, technical = research_fixture()
        rows = {r["id"]: r for r in build(tiers, technical)["products"]}
        for product_id in (
            "glet_mesterul_manole_8kg",
            "romanita_7kg",
            "sansiro_7kg",
        ):
            self.assertEqual(rows[product_id]["priority"], "P1")
            self.assertEqual(
                rows[product_id]["decision"], "blocked_technical"
            )

    def test_source_outage_is_reported_not_approved(self):
        tiers, technical = research_fixture()
        tiers["products"][0]["status"] = "held"
        tiers["products"][0]["candidateMedianMDL"] = None
        report = build(tiers, technical)
        self.assertEqual(report["summary"]["approvedForPublication"], 0)
        self.assertEqual(len(report["products"]), 6)

    def test_unexpected_approval_fails_closed(self):
        tiers, technical = research_fixture()
        tiers["products"][0]["tierQualityReviewed"] = True
        with self.assertRaisesRegex(ValueError, "approved"):
            build(tiers, technical)

    def test_missing_or_duplicate_product_fails_closed(self):
        tiers, technical = research_fixture()
        tiers["products"].append(deepcopy(tiers["products"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build(tiers, technical)


class TechnicalPublicationGuardTests(unittest.TestCase):
    def test_putty_and_paint_cannot_be_proposed_or_staged(self):
        scenarios = (
            ("finishPutty", 8, (200, 202)),
            ("interiorPaint", 7, (354, 356)),
        )

        for material, weight, prices in scenarios:
            with self.subTest(material=material):
                data = guarded_fixture(material, weight, prices)
                planned, proposed_catalog = plan(*data, now=NOW)
                row = planned["materials"][0]

                self.assertIn("standard", row["matchingPackTiers"])
                self.assertEqual(row["status"], "held")
                self.assertEqual(
                    row["reason"],
                    "manufacturer_scope_consumption_and_tier_review_not_approved",
                )
                self.assertEqual(planned["proposedCount"], 0)
                self.assertEqual(proposed_catalog, data[0])

                readiness, staged = prepare(*data, now=NOW)
                self.assertIsNone(staged)
                self.assertEqual(readiness["status"], "held")
                self.assertEqual(readiness["proposedPriceChanges"], 0)


if __name__ == "__main__":
    unittest.main()