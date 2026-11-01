"""Six additional retail products match existing COSTARO package sizes.

This only pins retailer pages/SKUs and physical pack metadata. It never
approves a quality tier or modifies prices.json.
"""

import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_prices import extract_price  # noqa: E402
from audit_material_pack_alignment import audit  # noqa: E402
from validate_app_catalog import load  # noqa: E402


EXPECTED = {
    "orizont_gypsum_plaster_30kg": (
        "gypsumPlaster", "bag", "packageWeightKg", 30,
        {"macons.md": "493", "domic.md": "190"},
    ),
    "supraton_extra_3kg": (
        "primer", "bucket", "packageWeightKg", 3,
        {"macons.md": "550", "domic.md": "247"},
    ),
    "kreisel_441_screed_25kg": (
        "floorScreedMix", "bag", "packageWeightKg", 25,
        {"macons.md": "1352", "domic.md": "1049"},
    ),
    "ceiling_metal_screws_100pcs": (
        "ceilingMetalScrews", "pack", "packageQuantity", 100,
        {"macons.md": "1731", "domic.md": "1428"},
    ),
    "ceiling_drywall_screws_200pcs": (
        "ceilingDrywallScrews", "pack", "packageQuantity", 200,
        {"macons.md": "1523", "domic.md": "1220"},
    ),
    "ceiling_joint_tape_45m": (
        "ceilingJointTape", "roll", "packageLengthM", 45,
        {"macons.md": "1082", "domic.md": "779"},
    ),
}


class ExactPackAlternativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = load(ROOT / "price_sources.json")
        cls.catalog = load(ROOT / "prices.json")
        cls.baseline = load(ROOT / "app_embedded_baseline.json")
        cls.items = {p["id"]: p for p in cls.sources["materials"]}

    def test_exact_pack_products_are_pinned_to_two_real_shop_skus(self):
        for identifier, (material, unit, field, amount, expected_skus) in EXPECTED.items():
            with self.subTest(product=identifier):
                product = self.items[identifier]
                self.assertEqual(product["catalogMaterialKey"], material)
                self.assertEqual(product["unit"], unit)
                self.assertEqual(product[field], amount)
                self.assertEqual({urlparse(s["url"]).hostname: s["productCode"]
                                  for s in product["sources"]}, expected_skus)
                self.assertTrue(all(s["url"].startswith("https://")
                                    for s in product["sources"]))
                self.assertIsNone(product["priceTier"])
                self.assertNotIn("tierCandidateForReview", product)

    def test_each_retailer_sku_requires_matching_product_identity(self):
        for identifier in EXPECTED:
            product = self.items[identifier]
            for source in product["sources"]:
                with self.subTest(product=identifier, shop=source["store"]):
                    sku = source["productCode"]
                    name = product["name"]
                    html = (
                        f'<h1>{name}</h1>'
                        f'<meta itemprop="sku" content="{sku}">'
                        '<meta itemprop="price" content="123.50">'
                    )
                    self.assertEqual(extract_price(html, product["matchTerms"],
                                                   sku, source["url"]),
                                     (123.5, "candidate", "product_microdata"))
                    self.assertEqual(extract_price(html, product["matchTerms"],
                                                   "wrong-sku", source["url"])[0], None)
                    self.assertEqual(extract_price(html, ["another product"],
                                                   sku, source["url"])[0], None)

    def test_existing_large_retail_packs_are_preserved_for_historical_review(self):
        old_ids = ("knauf_mp75_25kg", "supraton_extra_15kg", "floorScreedMix",
                   "ceilingMetalScrews", "ceilingDrywallScrews", "ceilingJointTape")
        self.assertTrue(all(identifier in self.items for identifier in old_ids))

    def test_added_pack_matches_never_publish_or_assign_quality_tiers(self):
        before = json.dumps(self.catalog, sort_keys=True, ensure_ascii=False)
        report = audit(self.catalog, self.baseline, self.sources)
        self.assertEqual(report["summary"]["catalogTierSlotsWithExactTwoShopMetadata"], 80)
        for row in report["products"]:
            if row["id"] in EXPECTED:
                self.assertFalse(row["reviewedTier"])
                self.assertFalse(row["approvedForPublication"])
        self.assertEqual(json.dumps(self.catalog, sort_keys=True, ensure_ascii=False), before)
        self.assertFalse(report["automaticPublicationEnabled"])


if __name__ == "__main__":
    unittest.main()
