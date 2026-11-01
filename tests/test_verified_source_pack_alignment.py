"""Safety checks for newly matched retail packages and explicit SKU URLs.

These checks deliberately do not approve budget/standard/premium placement
or publish a new prices.json file.
"""

import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_prices import extract_primary_microdata_price  # noqa: E402
from plan_verified_material_updates import _pack_tiers  # noqa: E402


class MatchedPackagingSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "prices.json").read_text(encoding="utf-8"))
        cls.config = json.loads((ROOT / "price_sources.json").read_text(encoding="utf-8"))
        cls.by_key = {item["catalogMaterialKey"]: item for item in cls.config["materials"]}

    def test_all_41_source_groups_remain_associated_with_known_catalog_keys(self):
        source_materials = self.config["materials"]
        self.assertEqual(len(source_materials), 41)
        self.assertEqual(len(self.by_key), 41)
        self.assertEqual(set(self.by_key), set(self.catalog["materialPrices"]))

    def test_finish_putty_and_paint_match_existing_catalog_packs(self):
        expected = {
            "finishPutty": ("glet_b62_satroc_8kg", 8),
            "interiorPaint": ("euroton_lav_7kg", 7),
        }
        for key, (identifier, weight) in expected.items():
            with self.subTest(material=key):
                source = self.by_key[key]
                self.assertEqual(source["id"], identifier)
                self.assertEqual(source["unit"], "bucket")
                self.assertEqual(source["packageWeightKg"], weight)
                self.assertEqual(_pack_tiers(self.catalog["materialPrices"][key], source),
                                 ["budget", "standard", "premium"])

    def test_each_matched_product_has_two_distinct_source_hosts(self):
        for key in ("finishPutty", "interiorPaint"):
            with self.subTest(material=key):
                sources = self.by_key[key]["sources"]
                self.assertEqual(len(sources), 2)
                names = {source["store"] for source in sources}
                hosts = {urlparse(source["url"]).hostname for source in sources}
                self.assertEqual(names, {"Macons", "ObraMag"})
                self.assertEqual(hosts, {"macons.md", "obramag.md"})
                for source in sources:
                    self.assertTrue(source["url"].startswith("https://"))
                    self.assertTrue(source["productCode"].strip())

    def test_scraper_can_strongly_match_verified_finish_putty_sku(self):
        terms = self.by_key["finishPutty"]["matchTerms"]
        html = ('<h1>Glet B-62 Satroc 8kg</h1>'
                '<meta itemprop="sku" content="513">'
                '<meta itemprop="price" content="191">')
        self.assertEqual(extract_primary_microdata_price(html, terms, "513"), 191)
        self.assertIsNone(extract_primary_microdata_price(html, terms, "wrong-sku"))
        self.assertIsNone(extract_primary_microdata_price(
            html.replace("8kg", "20kg"), terms, "513"))

    def test_scraper_can_strongly_match_verified_paint_sku(self):
        terms = self.by_key["interiorPaint"]["matchTerms"]
        html = ('<h1>Vopsea interior Supraten EUROTON LAV 7kg</h1>'
                '<meta itemprop="sku" content="350014">'
                '<meta itemprop="price" content="325">')
        self.assertEqual(extract_primary_microdata_price(html, terms, "350014"), 325)
        self.assertIsNone(extract_primary_microdata_price(
            html.replace("EUROTON", "SANSIRO"), terms, "350014"))

    def test_no_price_level_or_publication_was_prematurely_approved(self):
        for key in ("finishPutty", "interiorPaint"):
            self.assertIsNone(self.by_key[key]["priceTier"])
        policy = json.loads((ROOT / "material_update_policy.json").read_text(encoding="utf-8"))
        self.assertIs(policy["enabled"], False)
        self.assertEqual(policy["approvedMappings"], [])
        self.assertEqual(self.catalog["status"], "draft")
        self.assertIs(self.catalog["automaticUpdatesEnabled"], False)


if __name__ == "__main__":
    unittest.main()
