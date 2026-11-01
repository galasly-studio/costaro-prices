"""Fail-closed pack-size and unit checks for all 41 catalog materials."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_material_pack_alignment import audit, _check_tier  # noqa: E402
from validate_app_catalog import load  # noqa: E402


class PackAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load(ROOT / "prices.json")
        cls.baseline = load(ROOT / "app_embedded_baseline.json")
        cls.sources = load(ROOT / "price_sources.json")

    def report(self, src=None):
        return audit(self.catalog, self.baseline, src or self.sources)

    def item(self, key):
        report = self.report()
        return next(p for p in report["products"] if p["id"] == key)

    def test_all_41_materials_45_products_and_123_tiers_audited(self):
        report = self.report()
        summary = report["summary"]
        self.assertEqual(summary["catalogMaterials"], 41)
        self.assertEqual(summary["productGroups"], 45)
        self.assertEqual(summary["catalogTierSlots"], 123)
        self.assertEqual(summary["productTierChecks"], 135)
        self.assertEqual(summary["checksByStatus"], {
            "exact": 97, "different_unit": 0, "different_pack": 17,
            "missing_size": 3, "conversion_review": 12, "unverified": 6,
        })
        self.assertEqual(summary["productsWithTwoConfiguredShops"], 34)
        self.assertEqual(summary["productsMissingSku"], 1)
        self.assertFalse(report["automaticPublicationEnabled"])
        self.assertFalse(report["pricesChanged"])
        self.assertTrue(all(not p["approvedForPublication"] for p in report["products"]))

    def test_product_dimensions_match_exact_catalog_packs(self):
        expectations = {
            "gypsumBoardCeiling": ("packageAreaM2", 3),
            "ceilingCdProfile": ("packageLengthM", 3),
            "ceilingUdProfile": ("packageLengthM", 3),
            "pvcSkirtingPiece": ("packageLengthM", 2.5),
            "mdfSkirtingPiece": ("packageLengthM", 2.4),
        }
        by_id = {p["id"]: p for p in self.sources["materials"]}
        for product_id, (field, value) in expectations.items():
            with self.subTest(product=product_id):
                self.assertEqual(by_id[product_id][field], value)
                row = self.item(product_id)
                self.assertEqual({t: check["status"] for t, check in
                                  row["tierChecks"].items()},
                                 {"budget": "exact", "standard": "exact", "premium": "exact"})

    def test_mismatched_stores_never_map_to_other_pack_sizes(self):
        blocked = {
            "ceilingMetalScrews": (1000, 100),
            "ceilingDrywallScrews": (1000, 200),
            "ceilingJointTape": (90, 45),
            "supraton_extra_15kg": (15, 3),
            "floorScreedMix": (40, 25),
        }
        for product_id, (retail, catalog) in blocked.items():
            with self.subTest(product=product_id):
                check = self.item(product_id)["tierChecks"]["standard"]
                self.assertEqual(check["status"], "different_pack")
                self.assertEqual(check["retailPackageAmount"], retail)
                self.assertEqual(check["catalogPackageAmount"], catalog)

    def test_kilogram_pack_must_match_each_tier_not_just_material(self):
        for product, expected in (("knauf_mp75_25kg", ("different_pack", "exact", "exact")),
                                  ("acryl_putz_st10_start_20kg", ("different_pack", "exact", "exact"))):
            row = self.item(product)
            self.assertEqual(tuple(row["tierChecks"][k]["status"]
                                   for k in ("budget", "standard", "premium")), expected)

    def test_pack_per_piece_and_roll_must_be_reviewed_for_conversion(self):
        for product in ("ceilingBaseAnchorPerPiece", "ceilingUdFastenerPerPiece",
                        "laminateUnderlayPerM2", "electricalLightingConnectorPerPoint"):
            row = self.item(product)
            self.assertTrue(all(x["status"] == "conversion_review"
                                for x in row["tierChecks"].values()))

    def test_no_source_and_missing_metadata_cannot_be_approved(self):
        frame = self.item("ceilingFrameFastenersPerM2")
        self.assertEqual(frame["configuredStores"], 0)
        self.assertTrue(all(x["reason"] == "no_retail_sources"
                            for x in frame["tierChecks"].values()))
        wallpaper = self.item("wallpaper")
        self.assertTrue(all(x["status"] == "missing_size"
                            for x in wallpaper["tierChecks"].values()))
        glue = self.item("wallpaperGlue")
        self.assertTrue(all(x["reason"] == "pack_contents_not_defined_in_catalog"
                            for x in glue["tierChecks"].values()))

    def test_unsupported_and_malformed_units_fail_closed(self):
        self.assertEqual(_check_tier("foo", {"unit": "L", "amount": 5}, {"unit": "bucket"})[0],
                         "unverified")
        self.assertEqual(_check_tier("primer", {"unit": "кг", "amount": 3},
                                     {"unit": "bucket", "packageWeightKg": True})[0],
                         "missing_size")
        self.assertEqual(_check_tier("tilePerM2", 199, {"unit": "roll"})[0],
                         "conversion_review")

    def test_duplicate_store_domain_or_unapproved_tier_rejected(self):
        for corruption in ("domain", "tier"):
            sources = deepcopy(self.sources)
            product = next(p for p in sources["materials"]
                           if p["id"] == "ceilingCdProfile")
            if corruption == "domain":
                product["sources"][1]["url"] = product["sources"][0]["url"]
                reason = "Duplicate retail domain"
            else:
                product["priceTier"] = "premium"
                reason = "without manual approval"
            with self.assertRaisesRegex(ValueError, reason):
                self.report(sources)

    def test_market_price_catalog_remain_identical(self):
        before = json.dumps(self.catalog, sort_keys=True, ensure_ascii=False)
        self.report()
        self.assertEqual(before, json.dumps(self.catalog, sort_keys=True, ensure_ascii=False))

    def test_github_logs_include_full_pack_audit_without_price_push(self):
        workflow = (ROOT / ".github/workflows/monthly-price-audit.yml").read_text(
            encoding="utf-8")
        self.assertIn("python3 scripts/audit_material_pack_alignment.py", workflow)
        self.assertIn("material_pack_alignment_report.json", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("git push", workflow)


if __name__ == "__main__":
    unittest.main()
