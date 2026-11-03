"""Network-free Stage 29 manufacturer quality research tests."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_material_quality_dossiers import build, markdown
from test_build_material_candidate_dossiers import research_fixture

NOW = datetime(2026, 11, 3, 15, tzinfo=timezone.utc)


class QualityDossierTests(unittest.TestCase):
    def fixture(self):
        return research_fixture()

    def test_three_candidates_without_quality_approval(self):
        tiers, technical = self.fixture()
        result = build(tiers, technical, now=NOW)

        self.assertEqual(result["summary"]["productsReviewed"], 3)
        self.assertEqual(
            result["summary"]["technicalPreliminaryMatches"], 3
        )
        self.assertEqual(result["summary"]["qualityTiersApproved"], 0)
        self.assertEqual(result["summary"]["approvedForPublication"], 0)
        self.assertTrue(all(
            row["qualityTierVerified"] is False
            for row in result["products"]
        ))

    def test_source_data_not_modified(self):
        tiers, technical = self.fixture()
        before = json.dumps(
            [tiers, technical],
            ensure_ascii=False,
            sort_keys=True,
        )
        build(tiers, technical, now=NOW)
        after = json.dumps(
            [tiers, technical],
            ensure_ascii=False,
            sort_keys=True,
        )
        self.assertEqual(before, after)

    def test_manufacturer_url_tamper_rejected(self):
        tiers, technical = self.fixture()
        row = next(
            r for r in technical["products"]
            if r["id"] == "euroton_lav_7kg"
        )
        row["manufacturerUrl"] = "https://example.md/paint"
        with self.assertRaisesRegex(ValueError, "mismatch"):
            build(tiers, technical, now=NOW)

    def test_wrong_pack_rejected(self):
        tiers, technical = self.fixture()
        row = next(
            r for r in technical["products"]
            if r["id"] == "glet_satroc_8kg"
        )
        row["packageWeightKg"] = 17
        with self.assertRaisesRegex(ValueError, "mismatch"):
            build(tiers, technical, now=NOW)

    def test_unexpected_tier_approval_rejected(self):
        tiers, technical = self.fixture()
        row = next(
            r for r in tiers["products"]
            if r["id"] == "glet_b62_satroc_8kg"
        )
        row["tierQualityReviewed"] = True
        with self.assertRaisesRegex(ValueError, "approval"):
            build(tiers, technical, now=NOW)

    def test_network_outage_never_approves_quality(self):
        tiers, technical = self.fixture()
        row = next(
            r for r in tiers["products"]
            if r["id"] == "euroton_lav_7kg"
        )
        row["status"] = "held"
        row["candidateMedianMDL"] = None
        row["sourceObservations"] = []

        result = build(tiers, technical, now=NOW)

        self.assertEqual(result["summary"]["qualityTiersApproved"], 0)
        self.assertFalse(any(
            p["approvedForPublication"] for p in result["products"]
        ))

    def test_stale_manufacturer_evidence_is_flagged(self):
        tiers, technical = self.fixture()
        future = datetime(2027, 4, 1, tzinfo=timezone.utc)

        result = build(tiers, technical, now=future)

        self.assertFalse(result["manufacturerEvidenceFresh"])
        self.assertTrue(all(
            row["manufacturerEvidenceFresh"] is False
            for row in result["products"]
        ))
        self.assertEqual(result["summary"]["qualityTiersApproved"], 0)

    def test_consumption_problem_is_not_hidden(self):
        tiers, technical = self.fixture()
        row = next(
            r for r in technical["products"]
            if r["id"] == "glet_satroc_8kg"
        )
        row["requiresConsumptionReview"] = True

        result = build(tiers, technical, now=NOW)
        candidate = next(
            p for p in result["products"]
            if p["id"] == "glet_satroc_8kg"
        )

        self.assertFalse(candidate["technicalPreliminaryMatch"])
        self.assertFalse(candidate["qualityTierVerified"])

    def test_markdown_is_explicitly_research_only(self):
        tiers, technical = self.fixture()
        report = build(tiers, technical, now=NOW)
        text = markdown(report)

        self.assertIn("Только исследование", text)
        self.assertIn("Качество утверждено", text)
        self.assertIn("SATROC", text)
        self.assertIn("не присваиваются автоматически", text)


if __name__ == "__main__":
    unittest.main()