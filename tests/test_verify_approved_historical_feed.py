"""Fail-closed one-time feed staging; research catalog must remain untouched."""

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from stage_initial_historical_catalog import stage  # noqa: E402
from validate_app_catalog import load  # noqa: E402
from verify_approved_historical_feed import main, verify  # noqa: E402


class ApprovedHistoricalFeedTests(unittest.TestCase):
    def setUp(self):
        self.research = load(ROOT / "prices.json")
        self.baseline = load(ROOT / "app_embedded_baseline.json")
        self.policy = load(ROOT / "material_update_policy.json")
        self.readiness, self.approved = stage(
            self.research, self.baseline, self.policy,
            acknowledged_audit_date="2026-08-30",
        )
        self.approved_bytes = (json.dumps(self.approved, ensure_ascii=False,
                                         indent=2) + "\n").encode("utf-8")
        self.manifest = {
            "status": "approved_historical_fallback",
            "decision": "option_1",
            "catalogVersion": "0.1.1",
            "historicalAuditDate": "2026-08-30",
            "currentMarketPricesVerified": False,
            "publishedToGitHub": False,
            "publishedToGooglePlay": False,
            "workingCatalogUnchanged": True,
            "sha256": hashlib.sha256(self.approved_bytes).hexdigest().upper(),
        }

    def check(self, **overrides):
        values = {
            "research": self.research,
            "embedded": self.baseline,
            "policy": self.policy,
            "approved": self.approved,
            "manifest": self.manifest,
            "readiness": self.readiness,
            "approved_bytes": self.approved_bytes,
        }
        values.update(overrides)
        return verify(**values)

    def test_approved_historical_snapshot_is_staged_without_price_changes(self):
        frozen = deepcopy(self.research)
        report = self.check()
        self.assertEqual(report["status"], "historical_feed_verified_for_manual_deployment")
        self.assertEqual(report["catalogVersion"], "0.1.1")
        self.assertEqual(report["sourceAuditDate"], "2026-08-30")
        self.assertEqual(report["materialRates"], 41)
        self.assertEqual(report["laborRates"], 37)
        self.assertFalse(report["currentMarketPricesVerified"])
        self.assertFalse(report["automaticPricePublicationApproved"])
        self.assertEqual(self.research, frozen)

    def test_wrong_sha_is_rejected(self):
        manifest = deepcopy(self.manifest)
        manifest["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            self.check(manifest=manifest)

    def test_tampered_price_rejected_even_if_sha_updated(self):
        approved = deepcopy(self.approved)
        approved["materialPrices"]["ceilingDirectHangerPerPiece"]["budget"] += 1
        altered = (json.dumps(approved, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        manifest = deepcopy(self.manifest)
        manifest["sha256"] = hashlib.sha256(altered).hexdigest().upper()
        with self.assertRaisesRegex(ValueError, "exact historical baseline"):
            self.check(approved=approved, approved_bytes=altered, manifest=manifest)

    def test_unapproved_or_reverified_claim_is_rejected(self):
        manifest = deepcopy(self.manifest)
        manifest["currentMarketPricesVerified"] = True
        with self.assertRaisesRegex(ValueError, "manifest mismatch"):
            self.check(manifest=manifest)

    def test_research_catalog_not_initial_draft_is_rejected(self):
        research = deepcopy(self.research)
        research["status"] = "published"
        research["automaticUpdatesEnabled"] = True
        with self.assertRaises(ValueError):
            self.check(research=research)

    def test_approval_policy_enabled_is_rejected(self):
        policy = deepcopy(self.policy)
        policy["enabled"] = True
        with self.assertRaisesRegex(ValueError, "fully disabled"):
            self.check(policy=policy)

    def test_cli_creates_new_files_but_never_overwrites(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, payload in (
                ("research.json", self.research),
                ("baseline.json", self.baseline),
                ("policy.json", self.policy),
                ("approved.json", self.approved),
                ("manifest.json", self.manifest),
                ("readiness.json", self.readiness),
            ):
                path = root / name
                # Preserve LF bytes on Windows too: the SHA-256 manifest is
                # computed from exact bytes, not platform-native newlines.
                path.write_bytes((json.dumps(payload, ensure_ascii=False,
                                             indent=2) + "\n").encode("utf-8"))
            candidate = root / "feed/prices.json"
            report = root / "decision.json"
            args = [
                "--research", str(root / "research.json"),
                "--baseline", str(root / "baseline.json"),
                "--policy", str(root / "policy.json"),
                "--approved", str(root / "approved.json"),
                "--manifest", str(root / "manifest.json"),
                "--readiness", str(root / "readiness.json"),
                "--candidate", str(candidate),
                "--report", str(report),
            ]
            self.assertEqual(main(args), 0)
            self.assertEqual(load(candidate), self.approved)
            self.assertEqual(load(report)["sourceAuditDate"], "2026-08-30")
            with self.assertRaises(FileExistsError):
                main(args)


if __name__ == "__main__":
    unittest.main()
