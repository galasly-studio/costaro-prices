"""Regression checks for the four unavailable/ambiguous November sources.

These tests use synthetic HTML and never contact a shop or publish prices.
"""

import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_prices import extract_price, extract_primary_microdata_price  # noqa: E402


def ld_product(name, sku, mpn, url, price, currency="MDL"):
    product = {
        "@context": "https://schema.org/", "@type": "Product",
        "name": name, "sku": sku, "mpn": mpn,
        "offers": {
            "@type": "Offer", "url": url,
            "priceCurrency": currency, "price": price,
        },
    }
    return '<script type="application/ld+json">' + json.dumps(product) + '</script>'


class RecoveredSourceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads((ROOT / "price_sources.json").read_text(encoding="utf-8"))
        cls.by_id = {row["id"]: row for row in config["materials"]}
        cls.config = config

    def test_domic_putty_matches_retail_mpn_not_page_sku(self):
        html = ld_product("Glet Mesterul Manole 8kg", "91", "240",
                          "https://domic.md/ro/glet-mesterul-manole-8kg/91", "167.00")
        self.assertEqual(extract_price(html, ["Mesterul Manole", "8kg"], "240"),
                         (167.0, "candidate", "structured_data"))
        self.assertEqual(extract_price(html, ["Mesterul Manole", "8kg"], "999")[1],
                         "unavailable")

    def test_domic_paint_matches_retail_mpn_not_page_sku(self):
        html = ld_product("Vopsea Romanita 7kg", "136", "285",
                          "https://domic.md/ro/vopsea-romanita-7kg/136", "214.00")
        self.assertEqual(extract_price(html, ["Romanita", "7kg"], "285"),
                         (214.0, "candidate", "structured_data"))
        self.assertEqual(extract_price(html, ["Romanita", "14kg"], "285")[1],
                         "unavailable")

    def test_docconstruct_primers_lowercase_currency_is_valid_mdl(self):
        html = ld_product("Grund Supraton Extra 15kg", "dc100", "dc100",
                          "https://docconstruct.md/ro/grund-supraton-extra-15kg/100",
                          "565.00", "mdl")
        self.assertEqual(extract_price(html, ["Supraton", "Extra", "15kg"], "dc100"),
                         (565.0, "candidate", "structured_data"))

    def test_jsonld_usd_is_not_mistaken_for_mdl(self):
        html = ld_product("Grund Supraton Extra 15kg", "dc100", "dc100",
                          "https://docconstruct.md/ro/grund-supraton-extra-15kg/100",
                          "565.00", "USD")
        self.assertEqual(extract_price(html, ["Supraton", "Extra", "15kg"], "dc100")[1],
                         "unavailable")

    def test_class_nas_obramag_headline_matches_split_terms_and_sku(self):
        source = self.by_id["tile_adhesive_class_nas_25kg"]
        html = ('<h1>Adeziv pentru gresie/faianta CLASS NAS gri 25kg</h1>'
                '<meta itemprop="sku" content="510014">'
                '<meta itemprop="price" content="111">')
        self.assertEqual(extract_primary_microdata_price(html, source["matchTerms"],
                                                         "510014"), 111)
        self.assertIsNone(extract_primary_microdata_price(html, source["matchTerms"],
                                                          "wrong-sku"))

    def test_replacements_have_independent_hosts_and_exact_known_skus(self):
        expected = {
            "supraton_extra_15kg": {
                "macons.md": "552", "docconstruct.md": "dc100",
            },
            "tile_adhesive_class_nas_25kg": {
                "macons.md": "495", "gebhardt.md": "510014",
                "obramag.md": "510014",
            },
        }
        for item_id, stores in expected.items():
            with self.subTest(product=item_id):
                item = self.by_id[item_id]
                hosts = {urlparse(src["url"]).hostname: src["productCode"]
                         for src in item["sources"]}
                self.assertEqual(hosts, stores)
                self.assertIsNone(item["priceTier"])

    def test_monitoring_counts_and_catalog_remain_draft(self):
        self.assertEqual(len(self.config["materials"]), 51)
        # Includes six additional exact-pack products from two shops each.
        self.assertEqual(sum(len(row["sources"]) for row in self.config["materials"]), 91)
        self.assertIs(self.config["automaticPublicationEnabled"], False)
        catalog = json.loads((ROOT / "prices.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["status"], "draft")
        self.assertFalse(catalog["automaticUpdatesEnabled"])


if __name__ == "__main__":
    unittest.main()
