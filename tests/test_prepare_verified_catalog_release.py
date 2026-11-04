"""Network-free tests: broad exact-pack support and gated staged publication."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_verified_material_updates import _pack_tiers, plan  # noqa: E402
from prepare_verified_catalog_release import prepare  # noqa: E402
from validate_app_catalog import load, validate  # noqa: E402


NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def fixture(*, material="gypsumPlaster", tier="standard", source_unit="bag",
            package_field="packageWeightKg", package_size=25, medians=(151, 153)):
    catalog = load(ROOT / "prices.json")
    baseline = load(ROOT / "app_embedded_baseline.json")
    catalog["status"] = "published"
    catalog["automaticUpdatesEnabled"] = True
    source = {"id": "two_shops_identical_sku", "catalogMaterialKey": material,
              "priceTier": tier, "unit": source_unit,
              "sources": [
                  {"store": "One", "url": "https://shop-one.md/product", "productCode": "one-123"},
                  {"store": "Two", "url": "https://shop-two.md/product", "productCode": "two-123"},
              ]}
    if package_field is not None:
        source[package_field] = package_size
    sources = {"country": "MD", "currency": "MDL", "materials": [source]}
    observations = {"country": "MD", "currency": "MDL",
                    "generatedAt": NOW.isoformat(), "materials": [{
                        "id": source["id"], "observations": [
                            {**shop, "status": "candidate", "price": medians[index],
                             "extractionMethod": "product_microdata"}
                            for index, shop in enumerate(source["sources"])
                        ]}]}
    policy = {"schemaVersion": 1, "enabled": True,
              "automaticPublicationApproved": True,
              "approvedMappings": [{"observationId": source["id"],
                                    "catalogMaterialKey": material, "tier": tier}]}
    return [catalog, baseline, sources, observations, policy]


class ExactPhysicalUnitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = load(ROOT / "prices.json")

    def exact(self, key, unit, size_field=None, size=None):
        source = {"catalogMaterialKey": key, "unit": unit}
        if size_field:
            source[size_field] = size
        return _pack_tiers(self.catalog["materialPrices"][key], source)

    def test_individual_piece(self):
        self.assertEqual(self.exact("ceilingDirectHangerPerPiece", "piece"),
                         ["budget", "standard", "premium"])

    def test_individual_square_metre(self):
        self.assertEqual(self.exact("vinylPerM2", "m2"),
                         ["budget", "standard", "premium"])

    def test_individual_metre(self):
        self.assertEqual(self.exact("electricalSocketCablePerM", "m"),
                         ["budget", "standard", "premium"])

    def test_exact_sheet(self):
        self.assertEqual(self.exact("gypsumBoardCeiling", "sheet", "packageAreaM2", 3),
                         ["budget", "standard", "premium"])

    def test_exact_profile_length(self):
        self.assertEqual(self.exact("ceilingCdProfile", "piece", "packageLengthM", 3),
                         ["budget", "standard", "premium"])

    def test_exact_pack_of_screws(self):
        self.assertEqual(self.exact("ceilingMetalScrews", "pack", "packageQuantity", 100),
                         ["budget", "standard", "premium"])

    def test_exact_tape_roll(self):
        self.assertEqual(self.exact("ceilingJointTape", "roll", "packageLengthM", 45),
                         ["budget", "standard", "premium"])

    def test_wallpaper_only_matching_roll_area(self):
        self.assertEqual(self.exact("wallpaper", "roll", "packageAreaM2", 5.3), ["budget"])
        self.assertEqual(self.exact("wallpaper", "roll", "packageAreaM2", 10.6),
                         ["standard", "premium"])

    def test_different_screw_pack_rejected(self):
        self.assertEqual(self.exact("ceilingMetalScrews", "pack", "packageQuantity", 200), [])

    def test_unverified_pack_unit_rejected(self):
        self.assertEqual(self.exact("wallpaperGlue", "pack"), [])

    def test_piece_per_point_conversion_rejected(self):
        self.assertEqual(self.exact("electricalLightingConnectorPerPoint", "piece"), [])

    def test_scaling_from_cable_roll_rejected(self):
        self.assertEqual(self.exact("electricalSocketCablePerM", "roll", "packageLengthM", 50), [])


class GuardedReleaseTests(unittest.TestCase):
    def test_verified_packaged_material_release_is_staged_not_mutated(self):
        data = fixture()
        frozen = json.dumps(data[0], sort_keys=True, ensure_ascii=False)
        report, candidate = prepare(*data, now=NOW)
        self.assertEqual(report["status"], "ready_for_guarded_publication")
        self.assertEqual(report["catalogVersionCandidate"], "0.1.1")
        self.assertEqual(report["proposedPriceChanges"], 1)
        self.assertEqual(candidate["sourceAuditDate"], data[0]["sourceAuditDate"])
        self.assertEqual(report["lastVerifiedPartialMaterialChangeDate"], "2026-11-01")
        self.assertTrue(report["globalCatalogAuditDatePreserved"])
        self.assertEqual(candidate["materialPrices"]["gypsumPlaster"]["standard"]["price"], 152)
        self.assertEqual(candidate["laborPrices"], data[0]["laborPrices"])
        self.assertEqual(candidate["laborStagePrices"], data[0]["laborStagePrices"])
        self.assertFalse(validate(candidate, data[1]))
        self.assertEqual(json.dumps(data[0], sort_keys=True, ensure_ascii=False), frozen)
        self.assertTrue(report["publishedCatalogUnchangedByPreparation"])

    def test_scalar_unit_reaches_plan_and_release_without_pack_conversion(self):
        data = fixture(material="ceilingDirectHangerPerPiece", tier="budget",
                       source_unit="piece", package_field=None, medians=(8.3, 8.5))
        planned, _ = plan(*data, now=NOW)
        self.assertEqual(planned["proposedCount"], 1)
        report, candidate = prepare(*data, now=NOW)
        self.assertEqual(report["status"], "ready_for_guarded_publication")
        self.assertEqual(candidate["materialPrices"]["ceilingDirectHangerPerPiece"]["budget"], 8.4)
        self.assertFalse(validate(candidate, data[1]))

    def test_disabled_publication_flag_never_emits_candidate(self):
        data = fixture()
        data[4].pop("automaticPublicationApproved")
        report, candidate = prepare(*data, now=NOW)
        self.assertIsNone(candidate)
        self.assertIn("explicit_automatic_publication_approval_missing", report["holdReasons"])
        self.assertIsNone(report["lastVerifiedPartialMaterialChangeDate"])

    def test_draft_catalog_cannot_bootstrap_itself(self):
        data = fixture()
        data[0]["status"] = "draft"
        data[0]["automaticUpdatesEnabled"] = False
        report, candidate = prepare(*data, now=NOW)
        self.assertIsNone(candidate)
        self.assertIn("initial_catalog_is_not_published_and_verified", report["holdReasons"])

    def test_disabled_tier_policy_blocks_release(self):
        data = fixture()
        data[4]["enabled"] = False
        report, candidate = prepare(*data, now=NOW)
        self.assertIsNone(candidate)
        self.assertIn("approved_tier_mapping_policy_is_disabled", report["holdReasons"])

    def test_stale_observations_block_release(self):
        data = fixture()
        data[3]["generatedAt"] = (NOW - timedelta(days=2)).isoformat()
        report, candidate = prepare(*data, now=NOW)
        self.assertIsNone(candidate)
        self.assertEqual(report["proposedPriceChanges"], 0)

    def test_missing_microdata_blocks_release(self):
        data = fixture()
        data[3]["materials"][0]["observations"][1]["extractionMethod"] = "visible_text"
        report, candidate = prepare(*data, now=NOW)
        self.assertIsNone(candidate)
        self.assertEqual(report["proposedPriceChanges"], 0)

    def test_malformed_approval_fails_closed(self):
        data = fixture()
        data[4]["approvedMappings"][0]["tier"] = "premium"
        report, candidate = prepare(*data, now=NOW)
        self.assertIsNone(candidate)
        self.assertEqual(report["proposedPriceChanges"], 0)

    def test_price_spread_blocks_release(self):
        data = fixture()
        data[3]["materials"][0]["observations"][0]["price"] = 105
        report, candidate = prepare(*data, now=NOW)
        self.assertIsNone(candidate)
        self.assertEqual(report["proposedPriceChanges"], 0)

    def test_last_patch_version_fails_loudly(self):
        data = fixture()
        data[0]["catalogVersion"] = "0.1.999999"
        with self.assertRaisesRegex(ValueError, "patch exhausted"):
            prepare(*data, now=NOW)


if __name__ == "__main__":
    unittest.main()
