"""Safety checks for newly matched retail packages and explicit SKU URLs.

These checks deliberately do not approve budget/standard/premium placement
or publish a new prices.json file.
"""

import json
from collections import defaultdict
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_prices import extract_primary_microdata_price  # noqa: E402
from audit_prices import comparison_counts  # noqa: E402
from plan_verified_material_updates import _pack_tiers  # noqa: E402


class MatchedPackagingSourcesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads((ROOT / "prices.json").read_text(encoding="utf-8"))
        cls.config = json.loads((ROOT / "price_sources.json").read_text(encoding="utf-8"))
        cls.by_key = defaultdict(list)
        cls.by_id = {}
        for item in cls.config["materials"]:
            cls.by_key[item["catalogMaterialKey"]].append(item)
            cls.by_id[item["id"]] = item

    def test_51_product_groups_remain_associated_with_41_catalog_keys(self):
        source_materials = self.config["materials"]
        self.assertEqual(len(source_materials), 51)
        self.assertEqual(len(self.by_key), 41)
        self.assertEqual(len(self.by_id), 51)
        self.assertEqual(set(self.by_key), set(self.catalog["materialPrices"]))

    def test_six_finish_putty_and_paint_candidates_match_existing_catalog_packs(self):
        expected = {
            "finishPutty": {
                "budget": "glet_mesterul_manole_8kg",
                "standard": "glet_b62_satroc_8kg",
                "premium": "glet_satroc_8kg",
            },
            "interiorPaint": {
                "budget": "romanita_7kg",
                "standard": "euroton_lav_7kg",
                "premium": "sansiro_7kg",
            },
        }
        for key, candidates in expected.items():
            self.assertEqual(len(self.by_key[key]), 3)
            for tier, identifier in candidates.items():
                with self.subTest(material=key, tier=tier):
                    source = self.by_id[identifier]
                    self.assertEqual(source["catalogMaterialKey"], key)
                    self.assertIsNone(source["priceTier"])
                    self.assertEqual(source["tierCandidateForReview"], tier)
                    self.assertEqual(source["unit"], "bucket")
                    self.assertEqual(source["packageWeightKg"], 8 if key == "finishPutty" else 7)
                    self.assertEqual(_pack_tiers(self.catalog["materialPrices"][key], source),
                                     ["budget", "standard", "premium"])

    def test_each_tier_candidate_has_two_distinct_source_hosts_and_skus(self):
        for key in ("finishPutty", "interiorPaint"):
            for product in self.by_key[key]:
                with self.subTest(material=key, product=product["id"]):
                    sources = product["sources"]
                    self.assertEqual(len(sources), 2)
                    names = {source["store"] for source in sources}
                    hosts = {urlparse(source["url"]).hostname for source in sources}
                    self.assertEqual(len(names), 2)
                    self.assertEqual(len(hosts), 2)
                    self.assertIn("macons.md", hosts)
                    for source in sources:
                        self.assertTrue(source["url"].startswith("https://"))
                        self.assertTrue(source["productCode"].strip())

    def test_candidate_skus_and_shop_domains_are_pinned(self):
        expected = {
            "glet_mesterul_manole_8kg": {"macons.md": "543", "domic.md": "240"},
            "glet_b62_satroc_8kg": {"macons.md": "513", "obramag.md": "370035"},
            "glet_satroc_8kg": {"macons.md": "518", "obramag.md": "6000120"},
            "romanita_7kg": {"macons.md": "588", "domic.md": "285"},
            "euroton_lav_7kg": {"macons.md": "583", "obramag.md": "350014"},
            "sansiro_7kg": {"macons.md": "591", "obramag.md": "6000231"},
        }
        for identifier, sku_by_host in expected.items():
            with self.subTest(product=identifier):
                observed = {
                    urlparse(src["url"]).hostname: src["productCode"]
                    for src in self.by_id[identifier]["sources"]
                }
                self.assertEqual(observed, sku_by_host)

    def test_scraper_can_strongly_match_verified_finish_putty_sku(self):
        terms = self.by_id["glet_b62_satroc_8kg"]["matchTerms"]
        html = ('<h1>Glet B-62 Satroc 8kg</h1>'
                '<meta itemprop="sku" content="513">'
                '<meta itemprop="price" content="191">')
        self.assertEqual(extract_primary_microdata_price(html, terms, "513"), 191)
        self.assertIsNone(extract_primary_microdata_price(html, terms, "wrong-sku"))
        self.assertIsNone(extract_primary_microdata_price(
            html.replace("8kg", "20kg"), terms, "513"))

    def test_scraper_can_strongly_match_verified_paint_sku(self):
        terms = self.by_id["euroton_lav_7kg"]["matchTerms"]
        html = ('<h1>Vopsea interior Supraten EUROTON LAV 7kg</h1>'
                '<meta itemprop="sku" content="350014">'
                '<meta itemprop="price" content="325">')
        self.assertEqual(extract_primary_microdata_price(html, terms, "350014"), 325)
        self.assertIsNone(extract_primary_microdata_price(
            html.replace("EUROTON", "SANSIRO"), terms, "350014"))

    def test_four_new_products_require_correct_main_heading_and_exact_sku(self):
        fixtures = [
            ("glet_mesterul_manole_8kg", "Glet Mesterul Manole 8kg", "543", 167),
            ("glet_satroc_8kg", "Glet Satroc 8kg", "518", 234),
            ("romanita_7kg", "Vopsea Romanita 7kg", "588", 214),
            ("sansiro_7kg", "Vopsea universala Supraten SANSIRO 7kg", "591", 414),
        ]
        for identifier, heading, code, price in fixtures:
            with self.subTest(product=identifier):
                terms = self.by_id[identifier]["matchTerms"]
                html = (f'<h1>{heading}</h1>'
                        f'<meta itemprop="sku" content="{code}">'
                        f'<meta itemprop="price" content="{price}">')
                self.assertEqual(extract_primary_microdata_price(html, terms, code), price)
                self.assertIsNone(extract_primary_microdata_price(html, terms, "other"))

    def test_new_sku_cannot_reuse_another_products_main_heading(self):
        html = ('<h1>Glet B-62 Satroc 8kg</h1>'
                '<meta itemprop="sku" content="518">'
                '<meta itemprop="price" content="234">')
        self.assertIsNone(extract_primary_microdata_price(
            html, self.by_id["glet_satroc_8kg"]["matchTerms"], "513"))
        html = ('<h1>Vopsea Romanita 14kg</h1>'
                '<meta itemprop="sku" content="588">'
                '<meta itemprop="price" content="380">')
        self.assertIsNone(extract_primary_microdata_price(
            html, self.by_id["romanita_7kg"]["matchTerms"], "588"))

    def test_multi_product_comparison_counts_unique_catalog_keys(self):
        rows = [
            {"catalogMaterialKey": "finishPutty", "comparisonReady": True},
            {"catalogMaterialKey": "finishPutty", "comparisonReady": True},
            {"catalogMaterialKey": "interiorPaint", "comparisonReady": True},
            {"catalogMaterialKey": "interiorPaint", "comparisonReady": False},
        ]
        self.assertEqual(comparison_counts(rows), (2, 3))

    def test_no_price_level_or_publication_was_prematurely_approved(self):
        for source in self.config["materials"]:
            self.assertIsNone(source.get("priceTier"))
        self.assertIs(self.config["automaticPublicationEnabled"], False)
        policy = json.loads((ROOT / "material_update_policy.json").read_text(encoding="utf-8"))
        self.assertIs(policy["enabled"], False)
        self.assertEqual(policy["approvedMappings"], [])
        self.assertEqual(self.catalog["status"], "draft")
        self.assertIs(self.catalog["automaticUpdatesEnabled"], False)


if __name__ == "__main__":
    unittest.main()
