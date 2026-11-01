"""Fail-closed checks for a real solid-wood floor skirting source."""

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_prices import extract_price, extract_nanu_per_piece_price  # noqa: E402


NANU_URL = (
    "https://nanu.md/amenajari-interioare/pardoseli/plinte-si-profile/"
    "9053460-plinta-pardoseala-oak-ellora-55-mm-x-m-40-buc-ellora.html"
)
TERMS = ["Plinta pardoseala", "Ellora", "55"]


def page(*, heading="Plinta pardoseala Oak Ellora 55 mm x m (40 buc) Ellora",
         code="9053460", price="35,00", unit="* pret per buc"):
    return (
        '<div class="other-products"><span>200,00 mdl</span></div>'
        f"<h1>{heading}</h1>"
        '<div class="product-shorts"><span>Lemn de stejar masiv</span></div>'
        '<div id="product" class="product-description">'
        f'<p class="product-model"><b>Articul</b>: {code}</p>'
        f'<p class="product-model"><b>Cod</b>: {code}</p>'
        '<div class="product-price">'
        f'<div class="for">{unit}</div>'
        f'<div class="price-new">{price}<b class="symbol"> mdl</b></div>'
        '</div></div>'
        '<div class="recommendations">'
        '<h2>Similar</h2><p>Plinta pardoseala Ellora 55</p>'
        '<span>1,00 mdl</span></div>'
    )


class NanuSkirtingTests(unittest.TestCase):
    def test_extract_only_main_product_per_piece(self):
        self.assertEqual(
            extract_price(page(), TERMS, "9053460", NANU_URL),
            (35.0, "candidate", "product_scoped_visible_text"),
        )

    def test_wrong_product_or_code_or_currency_fails_closed(self):
        cases = [
            page(code="9053461"),
            page(heading="Plinta PVC Ellora 55"),
            page(price="35,00 EUR"),
            page(price="0"),
            page(unit="* pret per ambalaj"),
            page().replace('<p class="product-model"><b>Cod</b>: 9053460</p>', ""),
            page().replace('id="product"', 'id="recommended"'),
        ]
        for html in cases:
            with self.subTest(html=html[100:160]):
                self.assertEqual(
                    extract_price(html, TERMS, "9053460", NANU_URL)[0:2],
                    (None, "unavailable"),
                )

    def test_multiple_primary_prices_are_rejected(self):
        html = page().replace(
            '</div></div><div class="recommendations">',
            '<div class="price-new">36,00 mdl</div>'
            '</div></div><div class="recommendations">',
        )
        self.assertIsNone(extract_nanu_per_piece_price(html, TERMS, "9053460"))

    def test_config_pins_real_wood_floor_skirting_and_catalog_length(self):
        sources = json.loads((ROOT / "price_sources.json").read_text(encoding="utf-8"))
        prices = json.loads((ROOT / "prices.json").read_text(encoding="utf-8"))
        by_id = {item["id"]: item for item in sources["materials"]}
        wood = by_id["woodSkirtingPiece"]
        self.assertEqual(wood["catalogMaterialKey"], "woodSkirtingPiece")
        self.assertEqual(wood["packageLengthM"], 2.5)
        self.assertEqual(wood["retailPackQuantity"], 40)
        self.assertEqual(wood["unit"], "piece")
        self.assertEqual(wood["matchTerms"], TERMS)
        self.assertEqual(wood["sources"], [
            {"store": "Nanu", "url": NANU_URL, "productCode": "9053460"}
        ])
        self.assertIsNone(wood["priceTier"])
        for tier in ("budget", "standard", "premium"):
            self.assertEqual(prices["materialPrices"]["woodSkirtingPiece"][tier]["amount"], 2.5)

    def test_composite_fasteners_is_not_misrepresented_as_one_sku(self):
        sources = json.loads((ROOT / "price_sources.json").read_text(encoding="utf-8"))
        by_id = {item["id"]: item for item in sources["materials"]}
        self.assertEqual(by_id["ceilingFrameFastenersPerM2"]["sources"], [])
        self.assertEqual(len(sources["materials"]), 45)
        self.assertEqual(sum(bool(item["sources"]) for item in sources["materials"]), 44)
        self.assertEqual(sum(len(item["sources"]) for item in sources["materials"]), 61)
        self.assertFalse(sources["automaticPublicationEnabled"])
        for item in sources["materials"]:
            self.assertIsNone(item.get("priceTier"))

    def test_publication_policy_stays_disabled(self):
        policy = json.loads((ROOT / "material_update_policy.json").read_text(encoding="utf-8"))
        self.assertIs(policy["enabled"], False)
        self.assertEqual(policy["approvedMappings"], [])


if __name__ == "__main__":
    unittest.main()
