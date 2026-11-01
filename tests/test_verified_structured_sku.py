"""Offline tests: verified primary product JSON-LD must never trust recommendations."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_prices import extract_price, same_product_url  # noqa: E402
from build_material_tier_review import build  # noqa: E402
from plan_verified_material_updates import plan  # noqa: E402
from test_build_material_tier_review import NOW as REVIEW_NOW, fixture  # noqa: E402
from test_plan_verified_material_updates import NOW, sample  # noqa: E402


TERMS = ["Element suspensie", "0.65mm", "60x125mm"]
MACONS_URL = "https://macons.md/element-suspensie-065mm-60x125mm"
DOMIC_URL = "https://domic.md/ro/element-suspensie-0-65mm-60x125mm/1543"
PRODUCT_NAME = "Element suspensie, 0.65mm, 60x125mm"


def product(*, code="1982", sku=None, mpn=None, name=PRODUCT_NAME,
            url=MACONS_URL, offer_url=None, price="3.20", currency="MDL"):
    entry = {"@type": "Product", "name": name}
    if sku is not None:
        entry["sku"] = sku
    elif code is not None:
        entry["sku"] = code
    if mpn is not None:
        entry["mpn"] = mpn
    if url is not None:
        entry["url"] = url
    offer = {"@type": "Offer", "price": price}
    if currency is not None:
        offer["priceCurrency"] = currency
    if offer_url is not None:
        offer["url"] = offer_url
    entry["offers"] = offer
    return entry


def page(*products, heading=PRODUCT_NAME):
    heading_html = "" if heading is None else "<h1>" + heading + "</h1>"
    return (heading_html + '<script type="application/ld+json">'
            + json.dumps(list(products)) + "</script>")


class VerifiedStructuredSkuTests(unittest.TestCase):
    def parse(self, *products, heading=PRODUCT_NAME, code="1982", url=MACONS_URL):
        return extract_price(page(*products, heading=heading), TERMS, code, url)

    def test_exact_macons_sku_product_heading_url_and_mdl(self):
        self.assertEqual(self.parse(product(offer_url=MACONS_URL)),
                         (3.2, "candidate", "product_structured_sku"))

    def test_exact_domic_mpn_even_when_site_sku_is_different(self):
        entry = product(sku="1543", mpn="1679", url=None, offer_url=DOMIC_URL)
        self.assertEqual(self.parse(entry, code="1679", url=DOMIC_URL),
                         (3.2, "candidate", "product_structured_sku"))

    def test_h1_with_nested_markup_is_supported(self):
        entry = product(offer_url=MACONS_URL)
        html = ('<h1>Element <span>suspensie</span>, 0.65mm, 60x125mm</h1>'
                '<script type="application/ld+json">'
                + json.dumps(entry) + '</script>')
        self.assertEqual(extract_price(html, TERMS, "1982", MACONS_URL)[2],
                         "product_structured_sku")

    def test_no_main_heading_is_research_only(self):
        self.assertEqual(self.parse(product(), heading=None)[2], "structured_data")

    def test_different_main_heading_is_research_only(self):
        self.assertEqual(self.parse(product(), heading="Another product")[2],
                         "structured_data")

    def test_duplicate_main_heading_is_research_only(self):
        html = page(product()) + "<h1>Other product</h1>"
        self.assertEqual(extract_price(html, TERMS, "1982", MACONS_URL)[2],
                         "structured_data")

    def test_no_sku_or_mpn_is_research_only(self):
        self.assertEqual(self.parse(product(code=None))[2], "structured_data")

    def test_wrong_sku_never_becomes_verified_price(self):
        self.assertEqual(self.parse(product(code="not-1982"))[:2],
                         (None, "unavailable"))

    def test_wrong_offer_url_is_research_only(self):
        self.assertEqual(self.parse(product(url=None,
                                            offer_url="https://macons.md/another-item"))[2],
                         "structured_data")

    def test_wrong_product_url_is_research_only(self):
        self.assertEqual(self.parse(product(url="https://macons.md/another-item"))[2],
                         "structured_data")

    def test_absent_product_and_offer_urls_is_research_only(self):
        self.assertEqual(self.parse(product(url=None))[2], "structured_data")

    def test_missing_explicit_currency_is_research_only(self):
        self.assertEqual(self.parse(product(currency=None))[2], "structured_data")

    def test_non_mdl_currency_cannot_be_used(self):
        self.assertEqual(self.parse(product(currency="EUR"))[:2],
                         (None, "unavailable"))

    def test_product_recommendations_cannot_promote_other_price(self):
        recommendation = product(code="999", price="9.99")
        self.assertEqual(self.parse(product(), recommendation)[2],
                         "structured_data")

    def test_matching_name_but_different_retail_sku_blocks_promotion(self):
        unrelated = product(code="unrelated", price="3.20")
        self.assertEqual(self.parse(product(), unrelated)[2], "structured_data")

    def test_ambiguous_product_prices_are_never_verified(self):
        self.assertEqual(self.parse(product(price="3.20"),
                                    product(price="4.10"))[:2],
                         (None, "ambiguous"))

    def test_url_identity_rejects_cross_host_and_different_query(self):
        self.assertTrue(same_product_url(MACONS_URL + "/", MACONS_URL))
        self.assertFalse(same_product_url("https://other.md/element-suspensie-065mm-60x125mm",
                                          MACONS_URL))
        self.assertFalse(same_product_url(MACONS_URL + "?variant=2", MACONS_URL))
        self.assertFalse(same_product_url("http://macons.md/element-suspensie-065mm-60x125mm",
                                          MACONS_URL))
        self.assertFalse(same_product_url(None, MACONS_URL))


class VerifiedStructuredPlanningTests(unittest.TestCase):
    def test_two_strong_independent_shops_may_generate_read_only_proposal(self):
        data = sample()
        for observation in data[3]["materials"][0]["observations"]:
            observation["extractionMethod"] = "product_structured_sku"
        before = deepcopy(data[0])
        result, _ = plan(*data, now=NOW)
        self.assertEqual(result["materials"][0]["status"], "proposed")
        self.assertEqual(data[0], before)
        self.assertFalse(result["publishedPricesChanged"])
        self.assertFalse(result["verifiedForPublication"])

    def test_mixed_old_unverified_structured_data_blocks_proposal(self):
        data = sample()
        data[3]["materials"][0]["observations"][0]["extractionMethod"] = (
            "product_structured_sku")
        data[3]["materials"][0]["observations"][1]["extractionMethod"] = (
            "structured_data")
        result, _ = plan(*data, now=NOW)
        self.assertEqual(result["materials"][0]["reason"],
                         "product_identity_not_strongly_verified")

    def test_policy_disabled_even_with_verified_sources(self):
        data = sample()
        data[4]["enabled"] = False
        for observation in data[3]["materials"][0]["observations"]:
            observation["extractionMethod"] = "product_structured_sku"
        result, _ = plan(*data, now=NOW)
        self.assertEqual(result["proposedCount"], 0)

    def test_repository_policy_and_catalog_still_unpublished(self):
        policy = json.loads((ROOT / "material_update_policy.json").read_text("utf-8"))
        catalog = json.loads((ROOT / "prices.json").read_text("utf-8"))
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["approvedMappings"], [])
        self.assertEqual(catalog["status"], "draft")
        self.assertFalse(catalog["automaticUpdatesEnabled"])

    def test_manual_tier_review_understands_strong_sku_but_never_approves_quality(self):
        data = fixture()
        for product in data[3]["materials"]:
            for observation in product["observations"]:
                observation["extractionMethod"] = "product_structured_sku"
        review = build(*data, now=REVIEW_NOW)
        identified = [row for row in review["products"]
                      if row["status"] == "manual_review_candidate"]
        self.assertEqual(len(identified), 6)
        self.assertTrue(all(not row["skuAndMethodReviewRequired"]
                            for row in identified))
        self.assertTrue(all(not row["tierQualityReviewed"]
                            and not row["approvedForPublication"]
                            for row in identified))


if __name__ == "__main__":
    unittest.main()
