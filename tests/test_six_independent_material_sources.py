"""Regression coverage for six cross-shop product observations."""

import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_prices import comparison_counts  # noqa: E402
from collect_prices import extract_price  # noqa: E402


SECOND_SHOP = {
    "optim_cement_plaster_25kg": (
        "https://domic.md/ro/tencuiala-pe-baza-de-ciment-optim-25kg/85",
        "234", 25, 95,
    ),
    "acryl_putz_st10_start_20kg": (
        "https://domic.md/ro/chit-acryl-putz-st10-start-20kg/717",
        "859", 20, 272,
    ),
    "wallpaperGlue": (
        "https://domic.md/ro/adeziv-tapete-supra-t-200g/273",
        "420", 0.2, 35,
    ),
    "grout": (
        "https://domic.md/ro/chit-de-rosturi-ceresit-ce-40-2kg/1661",
        "1773", 2, 175,
    ),
    "floorScreedMix": (
        "https://domic.md/ro/sapa-egalizare-baumit-solido-e225-interior-exterior-12-80mm-40kg/1441",
        "1577", 40, 200,
    ),
    "floorWaterproofing": (
        "https://domic.md/ro/hidroizolatie-ceresit-cl-51-express-5kg/1610",
        "1735", 5, 799,
    ),
}


class SecondShopMaterialTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "price_sources.json").read_text(encoding="utf-8"))
        cls.products = {row["id"]: row for row in cls.config["materials"]}

    def test_six_exact_shop_urls_and_packaging(self):
        for product_id, (url, code, weight_kg, _price) in SECOND_SHOP.items():
            with self.subTest(product=product_id):
                product = self.products[product_id]
                shops = product["sources"]
                self.assertEqual(len(shops), 2)
                self.assertEqual(shops[1], {
                    "store": "Domic", "url": url, "productCode": code,
                })
                self.assertEqual(product["packageWeightKg"], weight_kg)
                self.assertIsNone(product["priceTier"])
                self.assertEqual(len({shop["store"] for shop in shops}), 2)
                self.assertEqual(len({urlparse(shop["url"]).hostname for shop in shops}), 2)
                self.assertTrue(all(shop["productCode"].strip() for shop in shops))

    def test_structured_parser_requires_exact_retail_code_and_item_name(self):
        for product_id, (url, code, _weight_kg, price) in SECOND_SHOP.items():
            with self.subTest(product=product_id):
                terms = self.products[product_id]["matchTerms"]
                name = " - ".join(terms)
                html = (
                    '<script type="application/ld+json">'
                    + json.dumps({
                        "@type": "Product", "name": name, "sku": "site-internal-id",
                        "mpn": code,
                        "offers": {"@type": "Offer", "priceCurrency": "MDL", "price": price},
                    })
                    + "</script>"
                )
                self.assertEqual(extract_price(html, terms, code, url),
                                 (price, "candidate", "structured_data"))
                self.assertEqual(extract_price(html, terms, "wrong-code", url)[0], None)
                self.assertEqual(extract_price(html, ["different product"], code, url)[0], None)

    def test_audit_has_six_more_comparable_product_groups(self):
        products = self.config["materials"]
        self.assertEqual(len(products), 45)
        # The November bulk pass added 18 matching alternative listings.
        self.assertEqual(sum(len(p["sources"]) for p in products), 79)
        self.assertEqual(len([p for p in products if p["sources"]]), 44)
        report_like_rows = [
            {"catalogMaterialKey": p["catalogMaterialKey"],
             "comparisonReady": len(p["sources"]) >= 2}
            for p in products
        ]
        self.assertEqual(comparison_counts(report_like_rows), (30, 34))

    def test_no_prices_or_policy_automatically_updated(self):
        catalog = json.loads((ROOT / "prices.json").read_text(encoding="utf-8"))
        policy = json.loads((ROOT / "material_update_policy.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["status"], "draft")
        self.assertFalse(catalog["automaticUpdatesEnabled"])
        self.assertFalse(self.config["automaticPublicationEnabled"])
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["approvedMappings"], [])
        self.assertTrue(all(p.get("priceTier") is None for p in self.config["materials"]))


if __name__ == "__main__":
    unittest.main()
