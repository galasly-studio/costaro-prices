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

    def test_all_41_materials_51_products_and_123_tiers_audited(self):
        report = self.report()
        summary = report["summary"]
        self.assertEqual(summary["catalogMaterials"], 41)
        self.assertEqual(summary["productGroups"], 51)
        self.assertEqual(summary["catalogTierSlots"], 123)
        self.assertEqual(summary["productTierChecks"], 153)
        self.assertEqual(summary["catalogTierSlotsWithExactTwoShopMetadata"], 80)
        self.assertEqual(summary["catalogMaterialsWithExactPacksForAllTiers"], 26)
        self.assertEqual(summary["checksByStatus"], {
            "exact": 113, "different_unit": 0, "different_pack": 19,
            "missing_size": 3, "conversion_review": 12, "unverified": 6,
        })
        self.assertEqual(summary["productsWithTwoConfiguredShops"], 40)
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

    def test_six_additional_shop_packs_match_catalog_without_approving_tiers(self):
        expected = {
            "orizont_gypsum_plaster_30kg": ("gypsumPlaster", ("exact", "different_pack", "different_pack")),
            "supraton_extra_3kg": ("primer", ("exact", "exact", "exact")),
            "kreisel_441_screed_25kg": ("floorScreedMix", ("exact", "exact", "exact")),
            "ceiling_metal_screws_100pcs": ("ceilingMetalScrews", ("exact", "exact", "exact")),
            "ceiling_drywall_screws_200pcs": ("ceilingDrywallScrews", ("exact", "exact", "exact")),
            "ceiling_joint_tape_45m": ("ceilingJointTape", ("exact", "exact", "exact")),
        }
        for product, (catalog_key, statuses) in expected.items():
            with self.subTest(product=product):
                item = self.item(product)
                self.assertEqual(item["catalogMaterialKey"], catalog_key)
                self.assertEqual(item["configuredStores"], 2)
                self.assertTrue(item["twoShopMetadataPresent"])
                self.assertFalse(item["retailSkuMissing"])
                self.assertEqual(tuple(item["tierChecks"][tier]["status"]
                                       for tier in ("budget", "standard", "premium")), statuses)
                self.assertFalse(item["reviewedTier"])
                self.assertFalse(item["approvedForPublication"])

    def test_new_shops_do_not_grant_retail_pack_quality_or_publication(self):
        rows = {r["catalogMaterialKey"]: r for r in self.report()["materials"]}
        for key in ("primer", "ceilingJointTape", "floorScreedMix"):
            for tier in ("budget", "standard", "premium"):
                self.assertTrue(rows[key]["tiers"][tier]["unitCompatibleWithTwoStores"])
                self.assertFalse(rows[key]["tiers"][tier]["qualityTierReviewed"])

    def test_live_market_confirmation_requires_comparison_ready_prices(self):
        market = {
            "country": "MD", "currency": "MDL", "status": "audit_only",
            "automaticPublicationEnabled": False, "publishedPricesChanged": False,
            "materials": [
                {"id": p["id"], "catalogMaterialKey": p["catalogMaterialKey"],
                 "comparisonReady": p["id"] != "ceiling_drywall_screws_200pcs"}
                for p in self.sources["materials"]
            ],
        }
        report = audit(self.catalog, self.baseline, self.sources, market)
        self.assertEqual(report["summary"]["catalogTierSlotsWithLiveComparableExactPacks"], 77)
        by_key = {row["catalogMaterialKey"]: row for row in report["materials"]}
        self.assertTrue(by_key["ceilingJointTape"]["tiers"]["standard"]["marketComparableExactProducts"])
        self.assertEqual(by_key["ceilingDrywallScrews"]["tiers"]["standard"]["marketComparableExactProducts"], [])
        self.assertFalse(report["pricesChanged"])

    def test_missing_or_untrusted_market_audit_is_rejected(self):
        market = {
            "country": "MD", "currency": "MDL", "status": "audit_only",
            "automaticPublicationEnabled": False, "publishedPricesChanged": False,
            "materials": [{"id": p["id"], "catalogMaterialKey": p["catalogMaterialKey"],
                           "comparisonReady": True} for p in self.sources["materials"]],
        }
        for corruption in ("missing", "duplicate", "country", "catalog_key"):
            bad = deepcopy(market)
            if corruption == "missing":
                bad["materials"].pop()
            elif corruption == "duplicate":
                bad["materials"].append(deepcopy(bad["materials"][0]))
            elif corruption == "country":
                bad["country"] = "ZZ"
            else:
                bad["materials"][0]["catalogMaterialKey"] = "different"
            with self.subTest(corruption=corruption):
                with self.assertRaises((ValueError, KeyError)):
                    audit(self.catalog, self.baseline, self.sources, bad)

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
