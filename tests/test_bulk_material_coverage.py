"""Read-only regression guard for the November 18-source coverage batch.

The mocked HTML is synthetic; these tests never contact a shop or approve a price.
"""

import json
from pathlib import Path
import sys
import unittest
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_prices import comparison_counts  # noqa: E402
from collect_prices import extract_price  # noqa: E402


# Each row is a distinct shop's exact model and pack, where listed.
EXTRA = {
    "ceilingDirectHangerPerPiece": ("Domic", "1679", "/element-suspensie-0-65mm-60x125mm/1543"),
    "ceilingExtensionConnectorPerPiece": ("Domic", "591", "/conector-imbinare-profiluri-cd-60x27/445"),
    "ceilingUdFastenerPerPiece": ("Domic", "787", "/diblu-cu-guler-cu-surub-cui-6x40mm-20buc/645"),
    "gypsumBoardCeiling": ("Domic", "2214", "/gips-carton-technogips-2500x1200x12-5mm/2104"),
    "ceilingCdProfile": ("Domic", "1509", "/profil-cd-60-27-0-6mm-3m/1373"),
    "ceilingUdProfile": ("Domic", "1436", "/profil-ud-27-28-0-6mm-3m/1300"),
    "ceilingMetalScrews": ("Domic", "1427", "/surub-autofiletant-pentru-metal-metal-3-5x9-5mm-1000buc/1291"),
    "ceilingDrywallScrews": ("Domic", "1221", "/surub-autofiletant-pentru-gips-metal-3-5x25mm-1000buc/1085"),
    "ceilingJointTape": ("Domic", "784", "/banda-pentru-rosturi-gips-carton-50mm-x-90m/642"),
    "electricalSocketCablePerM": ("Domic", "1656", "/cablu-electric-vvg-ng-3x2-5mm2/1520"),
    "electricalLightingCablePerM": ("Domic", "1657", "/cablu-electric-vvg-ng-3x1-5mm2/1521"),
    "electricalSocketPerPiece": ("Volta", "EPH2900221", "/produs/priza-schneider-eph2900221-250-v"),
    "electricalSwitchPerPiece": ("Volta", "8001-01", "/produs/intrerupator-unitar-elmos-8001-01-230-v"),
    "electricalLightingConnectorPerPoint": ("Panlight", "221-413", "/ro/materiale-pentru-electro-instalare-si-izolare/conectori-pentru-cablu/clema-wago-3x40mm2-221-413--221-413.html"),
    "mdfSkirtingPiece": ("Finisaj", "MP1101", "/collections/plintus-md-plinte-mdf/products/plinta-mdf-arbiton-mp1101-paint-it"),
    "pvcSkirtingPiece": ("Dekora", "CHW00001080", "/ro/product/plinta-indo-03-stejar-loft"),
    "decorativePlaster": ("Domic", "2289", "/tencuiala-decorativa-vinarom-f15-bob-de-orez-alb-25kg/2189"),
    "vinylPerM2": ("Veritan", "", "/ro/catalog/laminat/laminat-ametista-spc-spanish-cedar-korichnevyjj-33-klass-1220kh180-mm-tolshhina-4-mm-2-6352-m2"),
}

REVIEW_PENDING = {
    "ceilingCrossConnectorPerPiece", "ceilingBaseAnchorPerPiece",
    "tilePerM2", "laminatePerM2", "linoleumPerM2",
    "laminateUnderlayPerM2", "skirtingAccessoryPerPiece",
    "electricalSubboxPerPiece", "ceilingFrameFastenersPerM2",
    "wallpaper", "woodSkirtingPiece",
}


class BulkCoverageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / "price_sources.json").read_text(encoding="utf-8"))
        cls.materials = {m["id"]: m for m in cls.config["materials"]}

    def test_all_18_source_pairs_are_exactly_scoped_to_two_hosts(self):
        self.assertEqual(len(EXTRA), 18)
        for material_id, (store, code, path) in EXTRA.items():
            with self.subTest(material=material_id):
                sources = self.materials[material_id]["sources"]
                self.assertEqual(len(sources), 2)
                self.assertEqual(sources[1]["store"], store)
                self.assertEqual(sources[1]["productCode"], code)
                expected_path = "/ro" + path if store == "Domic" else path
                self.assertEqual(urlparse(sources[1]["url"]).path, expected_path)
                self.assertEqual(len({s["store"].lower() for s in sources}), 2)
                self.assertEqual(len({urlparse(s["url"]).hostname for s in sources}), 2)
                self.assertTrue(all(s["url"].startswith("https://") for s in sources))
                self.assertIsNone(self.materials[material_id]["priceTier"])

    def test_structured_candidates_still_require_exact_name_and_sku(self):
        for material_id, (_, code, _) in EXTRA.items():
            if not code:
                continue  # Veritan HTML has no advertised SKU: review-only candidate.
            with self.subTest(material=material_id):
                product = self.materials[material_id]
                src = product["sources"][1]
                terms = src.get("matchTerms", product["matchTerms"])
                html = '<script type="application/ld+json">' + json.dumps({
                    "@type": "Product", "name": " ".join(terms),
                    "sku": code, "offers": {
                        "price": "100", "priceCurrency": "MDL"
                    }
                }) + "</script>"
                self.assertEqual(
                    extract_price(html, terms, code, src["url"]),
                    (100.0, "candidate", "structured_data"),
                )
                self.assertEqual(
                    extract_price(html, terms, "wrong-sku", src["url"])[0],
                    None,
                )
                self.assertEqual(
                    extract_price(html, ["unrelated product"], code, src["url"])[0],
                    None,
                )

    def test_unresolved_11_remain_under_review_without_approving_tiers(self):
        self.assertEqual(len(REVIEW_PENDING), 11)
        for item_id in REVIEW_PENDING:
            with self.subTest(material=item_id):
                item = self.materials[item_id]
                self.assertLess(len(item["sources"]), 2)
                self.assertIsNone(item.get("priceTier"))
        self.assertEqual(self.materials["ceilingFrameFastenersPerM2"]["sources"], [])
        self.assertEqual(self.materials["laminatePerM2"]["sources"][0]["store"], "Gebhardt")

    def test_coverage_counts_and_catalog_publication_guard(self):
        materials = list(self.materials.values())
        self.assertEqual(len(materials), 51)
        self.assertEqual(sum(len(m["sources"]) for m in materials), 91)
        self.assertEqual(sum(bool(m["sources"]) for m in materials), 50)
        rows = [{"catalogMaterialKey": m["catalogMaterialKey"],
                 "comparisonReady": len(m["sources"]) > 1}
                for m in materials]
        self.assertEqual(comparison_counts(rows), (30, 40))
        self.assertFalse(self.config["automaticPublicationEnabled"])
        self.assertTrue(all(m.get("priceTier") is None for m in materials))
        catalog = json.loads((ROOT / "prices.json").read_text(encoding="utf-8"))
        policy = json.loads((ROOT / "material_update_policy.json").read_text(encoding="utf-8"))
        self.assertEqual(catalog["status"], "draft")
        self.assertFalse(catalog["automaticUpdatesEnabled"])
        self.assertFalse(policy["enabled"])
        self.assertEqual(policy["approvedMappings"], [])


if __name__ == "__main__":
    unittest.main()
