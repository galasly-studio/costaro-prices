"""Stage 28: fail-closed ObraMag primary-card price extraction tests."""

import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from collect_prices import (
    OBRAMAG_SCOPED_RESEARCH,
    extract_price,
)
from plan_verified_material_updates import plan
from test_plan_verified_material_updates import NOW, sample


CASES = (
    (
        "glet_b62_satroc_8kg",
        "Glet finisare acril B-62 SATROC 8kg",
        "370035",
        191.0,
    ),
    (
        "glet_satroc_8kg",
        "Glet finisare acril SATROC 8kg",
        "6000120",
        234.0,
    ),
    (
        "euroton_lav_7kg",
        "Vopsea interior Supraten EUROTON LAV 7kg",
        "350014",
        325.0,
    ),
)


def html_card(name, code, price, *, unit="cal", footer=""):
    return (
        "<header><div>Publicitate: 999,00MDL</div></header>"
        "<main>"
        f"<h1>{name}</h1>"
        f"<div>Cod produs: <strong>{code}</strong></div>"
        "<div>În stoc</div>"
        "<div>Preț</div>"
        f"<strong>{price:.2f}MDL / {unit}</strong>"
        "<label>Cantitate</label>"
        "</main>"
        + footer
    )


class ObraMagPrimaryCardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        config = json.loads(
            (ROOT / "price_sources.json").read_text(encoding="utf-8")
        )
        cls.sources = {p["id"]: p for p in config["materials"]}

    def source(self, product_id):
        material = self.sources[product_id]
        shop = next(
            source for source in material["sources"]
            if source["store"] == "ObraMag"
        )
        return material, shop

    def test_three_pinned_retail_sources_are_exact(self):
        for product_id, name, code, _price in CASES:
            with self.subTest(product_id=product_id):
                material, shop = self.source(product_id)
                self.assertEqual(shop["productCode"], code)
                self.assertEqual(material["name"], name)
                self.assertEqual(
                    OBRAMAG_SCOPED_RESEARCH[
                        "/" + shop["url"].split("/", 3)[3]
                    ],
                    code,
                )
                self.assertIsNone(material["priceTier"])

    def test_exact_main_card_is_research_only(self):
        for product_id, name, code, price in CASES:
            with self.subTest(product_id=product_id):
                material, shop = self.source(product_id)
                html = html_card(
                    name, code, price,
                    footer=(
                        "<aside>"
                        "<h3>Похожие товары</h3>"
                        "Cod produs: 999999"
                        "Preț 10,00MDL / cal"
                        "</aside>"
                    ),
                )
                self.assertEqual(
                    extract_price(
                        html,
                        material["matchTerms"],
                        code,
                        shop["url"],
                    ),
                    (
                        price,
                        "candidate",
                        "product_scoped_visible_text",
                    ),
                )

    def test_wrong_main_sku_is_rejected(self):
        for product_id, name, code, price in CASES:
            with self.subTest(product_id=product_id):
                material, shop = self.source(product_id)
                output = extract_price(
                    html_card(name, "UNRELATED", price),
                    material["matchTerms"],
                    code,
                    shop["url"],
                )
                self.assertEqual(output[0], None)
                self.assertEqual(output[1], "unavailable")

    def test_wrong_heading_is_rejected(self):
        material, shop = self.source(CASES[0][0])
        self.assertIsNone(
            extract_price(
                html_card("Другой продукт 8kg", CASES[0][2], 191),
                material["matchTerms"],
                CASES[0][2],
                shop["url"],
            )[0]
        )

    def test_recommended_product_cannot_supply_missing_price(self):
        material, shop = self.source(CASES[0][0])
        html = (
            f"<h1>{CASES[0][1]}</h1>"
            f"<div>Cod produs: {CASES[0][2]}</div>"
            "<label>Cantitate</label>"
            "<aside><h3>Recommended</h3>"
            "Preț 191,00MDL / cal</aside>"
        )
        self.assertIsNone(
            extract_price(
                html,
                material["matchTerms"],
                CASES[0][2],
                shop["url"],
            )[0]
        )

    def test_two_main_prices_are_ambiguous_and_rejected(self):
        material, shop = self.source(CASES[0][0])
        html = (
            f"<h1>{CASES[0][1]}</h1>"
            f"<div>Cod produs: {CASES[0][2]}</div>"
            "<div>Preț 191,00MDL / cal</div>"
            "<div>Preț 175,00MDL / cal</div>"
            "<label>Cantitate</label>"
        )
        self.assertIsNone(
            extract_price(
                html,
                material["matchTerms"],
                CASES[0][2],
                shop["url"],
            )[0]
        )

    def test_wrong_pack_unit_is_rejected(self):
        material, shop = self.source(CASES[0][0])
        self.assertIsNone(
            extract_price(
                html_card(CASES[0][1], CASES[0][2], 191, unit="kg"),
                material["matchTerms"],
                CASES[0][2],
                shop["url"],
            )[0]
        )

    def test_unapproved_code_change_is_rejected(self):
        material, shop = self.source(CASES[0][0])
        self.assertIsNone(
            extract_price(
                html_card(CASES[0][1], CASES[0][2], 191),
                material["matchTerms"],
                "CHANGED-CODE",
                shop["url"],
            )[0]
        )

    def test_duplicate_primary_h1_is_rejected(self):
        material, shop = self.source(CASES[0][0])
        html = html_card(CASES[0][1], CASES[0][2], 191)
        html += "<h1>Other product</h1>"
        self.assertIsNone(
            extract_price(
                html,
                material["matchTerms"],
                CASES[0][2],
                shop["url"],
            )[0]
        )

    def test_fake_script_data_cannot_supply_price(self):
        material, shop = self.source(CASES[0][0])
        html = (
            f"<h1>{CASES[0][1]}</h1>"
            f"<div>Cod produs: {CASES[0][2]}</div>"
            "<script>document.write('Preț 191,00MDL / cal')</script>"
            "<label>Cantitate</label>"
        )
        self.assertIsNone(
            extract_price(
                html,
                material["matchTerms"],
                CASES[0][2],
                shop["url"],
            )[0]
        )

    def test_scoped_visible_quote_cannot_approve_catalog(self):
        data = sample()
        data[3]["materials"][0]["observations"][1][
            "extractionMethod"
        ] = "product_scoped_visible_text"

        planned, _candidate = plan(*data, now=NOW)

        self.assertEqual(planned["proposedCount"], 0)
        self.assertEqual(
            planned["materials"][0]["reason"],
            "product_identity_not_strongly_verified",
        )
        self.assertFalse(planned["verifiedForPublication"])


if __name__ == "__main__":
    unittest.main()