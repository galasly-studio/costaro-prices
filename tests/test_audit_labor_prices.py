import copy
from datetime import date
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_labor_prices import LABOR_KEYS, audit, catalog_errors


def catalog():
    return {
        "schemaVersion": 1,
        "catalogVersion": "0.1.0",
        "country": "MD",
        "currency": "MDL",
        "status": "draft",
        "automaticUpdatesEnabled": False,
        "laborPrices": {
            key: {"budget": 30, "standard": 45, "premium": 60}
            for key in LABOR_KEYS
        },
        "materialPrices": {f"material_{n}": {} for n in range(41)},
        "laborStagePrices": {
            "startPuttyWork": {"budget": 40, "standard": 55, "premium": 80}
        },
    }


def quote(url, *, checked="2026-10-31", scope="puttyWork", low=35, high=85):
    return {
        "url": url, "checkedOn": checked, "scope": scope,
        "unit": "m2", "min": low, "max": high,
    }


class LaborAuditTests(unittest.TestCase):
    today = date(2026, 10, 31)

    def test_valid_catalog_has_37_labor_keys(self):
        self.assertEqual(catalog_errors(catalog()), [])
        self.assertEqual(len(LABOR_KEYS), 37)

    def test_no_sources_cannot_be_called_market_verified(self):
        report = audit(catalog(), {"sources": {}}, self.today)
        self.assertTrue(report["ok"])
        self.assertEqual(report["readyCount"], 0)
        self.assertEqual(report["needsReviewCount"], 37)
        self.assertEqual(report["startPuttyMarketStatus"], "NEEDS REVIEW")

    def test_two_independent_sources_enable_comparison(self):
        refs = {"sources": {"puttyWork": [
            quote("https://one.md/prices"),
            quote("https://two.md/prices"),
        ]}}
        report = audit(catalog(), refs, self.today)
        row = next(r for r in report["rows"] if r["key"] == "puttyWork")
        self.assertEqual(row["status"], "COMPARISON READY")
        self.assertEqual(report["readyCount"], 1)

    def test_two_pages_on_same_domain_are_one_source(self):
        refs = {"sources": {"puttyWork": [
            quote("https://example.md/prices/1"),
            quote("https://www.example.md/prices/2"),
        ]}}
        report = audit(catalog(), refs, self.today)
        self.assertEqual(report["readyCount"], 0)

    def test_stale_and_unmatched_source_never_count(self):
        refs = {"sources": {"puttyWork": [
            quote("https://one.md/prices", checked="2025-01-01"),
            quote("https://two.md/prices", scope="plasterWork"),
        ]}}
        report = audit(catalog(), refs, self.today)
        self.assertEqual(report["readyCount"], 0)

    def test_wrong_unit_cannot_count_as_source(self):
        first = quote("https://one.md/prices")
        first["unit"] = "piece"  # puttyWork requires m2
        refs = {"sources": {"puttyWork": [
            first, quote("https://two.md/prices"),
        ]}}
        report = audit(catalog(), refs, self.today)
        self.assertEqual(report["readyCount"], 0)

    def test_out_of_range_standard_flags_manual_review(self):
        refs = {"sources": {"puttyWork": [
            quote("https://one.md/prices", low=100, high=110),
            quote("https://two.md/prices", low=100, high=110),
        ]}}
        report = audit(catalog(), refs, self.today)
        row = next(r for r in report["rows"] if r["key"] == "puttyWork")
        self.assertEqual(row["status"], "NEEDS REVIEW")
        self.assertIn("standard_price_outside_observed_range", row["warnings"])

    def test_missing_labor_key_rejected(self):
        data = catalog()
        del data["laborPrices"][LABOR_KEYS[0]]
        self.assertTrue(catalog_errors(data))

    def test_extra_labor_key_rejected(self):
        data = catalog()
        data["laborPrices"]["startPuttyWork"] = {"budget": 40, "standard": 55, "premium": 80}
        self.assertTrue(catalog_errors(data))

    def test_tier_inversion_rejected(self):
        data = catalog()
        data["laborPrices"]["puttyWork"]["premium"] = 10
        self.assertTrue(catalog_errors(data))

    def test_invalid_stage_rejected(self):
        data = catalog()
        data["laborStagePrices"]["startPuttyWork"]["standard"] = 99
        self.assertTrue(catalog_errors(data))

    def test_published_catalog_rejected_for_draft_audit(self):
        data = catalog()
        data["status"] = "published"
        data["automaticUpdatesEnabled"] = True
        self.assertTrue(catalog_errors(data))

    def test_audit_does_not_modify_prices(self):
        data = catalog()
        before = copy.deepcopy(data)
        audit(data, {"sources": {}}, self.today)
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
