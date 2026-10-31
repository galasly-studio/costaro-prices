"""Regression checks matching COSTARO's published catalog guardrails."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT / "scripts"))

from validate_app_catalog import load, validate, version_valid


def original():
    return load(PROJECT / "app_embedded_baseline.json")


class AppCatalogCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.baseline = original()
        self.catalog = deepcopy(self.baseline)

    def check_error(self, fragment):
        errors = validate(self.catalog, self.baseline)
        self.assertTrue(any(fragment in entry for entry in errors), errors)

    def test_unmodified_draft_is_valid(self):
        self.assertEqual(validate(self.catalog, self.baseline), [])

    def test_published_with_enabled_updates_is_valid(self):
        self.catalog["status"] = "published"
        self.catalog["automaticUpdatesEnabled"] = True
        self.assertEqual(validate(self.catalog, self.baseline), [])

    def test_published_but_disabled_is_rejected(self):
        self.catalog["status"] = "published"
        self.check_error("status/automaticUpdatesEnabled")

    def test_draft_with_updates_enabled_is_rejected(self):
        self.catalog["automaticUpdatesEnabled"] = True
        self.check_error("status/automaticUpdatesEnabled")

    def test_wrong_metadata_is_rejected(self):
        self.catalog["currency"] = "EUR"
        self.check_error("country and currency")

    def test_invalid_version_is_rejected(self):
        for invalid in ("0.1", "01.1.0", "0.1.1000000", "nan"):
            self.catalog["catalogVersion"] = invalid
            self.check_error("catalogVersion")
        self.assertTrue(version_valid("0.1.1"))

    def test_one_labor_price_within_30_percent_is_valid(self):
        self.catalog["laborPrices"]["wallPaintWork"]["standard"] = 55
        self.assertEqual(validate(self.catalog, self.baseline), [])

    def test_labor_price_above_baseline_limit_is_rejected(self):
        self.catalog["laborPrices"]["wallPaintWork"]["standard"] = 100
        self.check_error("more than 30%")

    def test_material_price_below_baseline_limit_is_rejected(self):
        self.catalog["materialPrices"]["tilePerM2"]["standard"] = 50
        self.check_error("more than 30%")

    def test_pack_quantity_cannot_change(self):
        self.catalog["materialPrices"]["gypsumPlaster"]["standard"]["amount"] = 50
        self.check_error("forbidden change of amount")

    def test_pack_name_cannot_change(self):
        self.catalog["materialPrices"]["gypsumPlaster"]["standard"]["name"] = "Other"
        self.check_error("forbidden change of name")

    def test_pack_price_within_limit_is_accepted(self):
        current = self.catalog["materialPrices"]["gypsumPlaster"]["standard"]
        current["price"] *= 1.05
        self.assertEqual(validate(self.catalog, self.baseline), [])

    def test_missing_catalog_key_is_rejected(self):
        del self.catalog["materialPrices"]["primer"]
        self.check_error("missing or unknown catalog keys")

    def test_extra_labor_key_is_rejected(self):
        self.catalog["laborPrices"]["newWork"] = deepcopy(
            self.catalog["laborPrices"]["puttyWork"]
        )
        self.check_error("missing or unknown catalog keys")

    def test_inverted_tiers_are_rejected(self):
        self.catalog["laborPrices"]["wallPaintWork"]["premium"] = 1
        self.check_error("budget <= standard <= premium")

    def test_start_putty_extension_must_remain(self):
        del self.catalog["laborStagePrices"]
        self.check_error("startPuttyWork must be preserved")

    def test_start_putty_labor_change_over_30_percent_is_rejected(self):
        self.catalog["laborStagePrices"]["startPuttyWork"]["standard"] = 100
        self.check_error("more than 30%")

    def test_boolean_price_is_rejected(self):
        self.catalog["laborPrices"]["wallPaintWork"]["standard"] = True
        self.check_error("finite positive")

    def test_boolean_schema_version_is_rejected(self):
        self.catalog["schemaVersion"] = True
        self.check_error("schemaVersion")

    def test_numeric_publish_flag_is_rejected(self):
        self.catalog["automaticUpdatesEnabled"] = 0
        self.check_error("status/automaticUpdatesEnabled")

    def test_boolean_package_quantity_is_rejected(self):
        self.catalog["materialPrices"]["wallpaperGlue"]["budget"]["amount"] = True
        self.check_error("forbidden change of amount")

    def test_validation_never_modifies_prices(self):
        snapshot = deepcopy(self.catalog)
        validate(self.catalog, self.baseline)
        self.assertEqual(self.catalog, snapshot)


if __name__ == "__main__":
    unittest.main()
