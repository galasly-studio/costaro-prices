"""One-time historical baseline preparation must never publish current prices."""

from copy import deepcopy
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage_initial_historical_catalog import main, stage  # noqa: E402
from validate_app_catalog import load, validate  # noqa: E402


class HistoricalBaselineStageTests(unittest.TestCase):
    def setUp(self):
        self.catalog = load(ROOT / "prices.json")
        self.baseline = load(ROOT / "app_embedded_baseline.json")
        self.policy = load(ROOT / "material_update_policy.json")

    def test_exact_historical_baseline_is_staged_without_market_claims(self):
        frozen = deepcopy(self.catalog)
        report, candidate = stage(
            self.catalog, self.baseline, self.policy,
            acknowledged_audit_date="2026-08-30",
        )
        self.assertEqual(report["status"], "historical_fallback_staged_for_manual_review")
        self.assertEqual(report["materialKeys"], 41)
        self.assertEqual(report["laborKeys"], 37)
        self.assertFalse(report["priceValuesChanged"])
        self.assertFalse(report["currentMarketPricesVerified"])
        self.assertFalse(report["automaticPublicationApproved"])
        self.assertTrue(report["requiresSeparateManualPromotion"])
        self.assertEqual(candidate["catalogVersion"], "0.1.1")
        self.assertEqual(candidate["status"], "published")
        self.assertTrue(candidate["automaticUpdatesEnabled"])
        self.assertEqual(candidate["sourceAuditDate"], "2026-08-30")
        self.assertEqual(candidate["materialPrices"], frozen["materialPrices"])
        self.assertEqual(candidate["laborPrices"], frozen["laborPrices"])
        self.assertEqual(candidate["laborStagePrices"], frozen["laborStagePrices"])
        self.assertEqual(self.catalog, frozen)
        self.assertEqual(validate(candidate, self.baseline), [])

    def test_incorrect_historical_date_cannot_be_silently_replaced(self):
        with self.assertRaisesRegex(ValueError, "audit date"):
            stage(self.catalog, self.baseline, self.policy,
                  acknowledged_audit_date="2026-11-04")

    def test_edited_material_price_blocks_bootstrap(self):
        self.catalog["materialPrices"]["ceilingDirectHangerPerPiece"]["budget"] += 1
        with self.assertRaisesRegex(ValueError, "exact frozen app baseline"):
            stage(self.catalog, self.baseline, self.policy,
                  acknowledged_audit_date="2026-08-30")

    def test_edited_labor_price_blocks_bootstrap(self):
        self.catalog["laborPrices"]["ceilingPaintWork"]["budget"] += 1
        with self.assertRaisesRegex(ValueError, "exact frozen app baseline"):
            stage(self.catalog, self.baseline, self.policy,
                  acknowledged_audit_date="2026-08-30")

    def test_live_policy_must_stay_disabled(self):
        self.policy["enabled"] = True
        with self.assertRaisesRegex(ValueError, "fully disabled"):
            stage(self.catalog, self.baseline, self.policy,
                  acknowledged_audit_date="2026-08-30")

    def test_existing_published_catalog_cannot_bootstrap_again(self):
        self.catalog["status"] = "published"
        self.catalog["automaticUpdatesEnabled"] = True
        with self.assertRaisesRegex(ValueError, "exact frozen app baseline"):
            stage(self.catalog, self.baseline, self.policy,
                  acknowledged_audit_date="2026-08-30")

    def test_staging_cli_refuses_to_overwrite_previous_outputs(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "staged_prices.json"
            report = root / "decision.json"
            args = [
                "--catalog", str(ROOT / "prices.json"),
                "--baseline", str(ROOT / "app_embedded_baseline.json"),
                "--policy", str(ROOT / "material_update_policy.json"),
                "--acknowledge-historical-audit-date", "2026-08-30",
                "--candidate", str(candidate),
                "--report", str(report),
            ]
            self.assertEqual(main(args), 0)
            self.assertTrue(candidate.is_file())
            self.assertTrue(report.is_file())
            self.assertEqual(json.loads(candidate.read_text(encoding="utf-8"))
                             ["sourceAuditDate"], "2026-08-30")
            with self.assertRaises(FileExistsError):
                main(args)


if __name__ == "__main__":
    unittest.main()
