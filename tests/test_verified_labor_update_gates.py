"""No-network regression: labor prices remain unchanged without full consent."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from plan_verified_labor_updates import plan  # noqa: E402
from prepare_verified_catalog_release import prepare  # noqa: E402
from validate_app_catalog import load, validate  # noqa: E402


NOW = datetime(2026, 11, 5, 11, tzinfo=timezone.utc)
SCOPE = "wall-paint-two-finish-coats-dry-room"


def fixture(*, stage=False):
    catalog = load(ROOT / "published_catalog/prices.json")
    baseline = load(ROOT / "published_catalog/compatibility_baseline.json")
    key = "startPuttyWork" if stage else "wallPaintWork"
    amount = 41 if stage else 24
    policy = {
        "schemaVersion": 1, "enabled": True,
        "automaticPublicationApproved": True,
        "approvedMappings": [{
            "workKey": key, "tier": "budget", "unit": "m2",
            "scopeId": SCOPE, "manuallyApproved": True,
            "approvedSourceDomains": ["builder-one.md", "builder-two.md"],
        }],
    }
    evidence = {
        "schemaVersion": 1, "country": "MD", "currency": "MDL",
        "generatedAt": NOW.isoformat(), "quotes": [
            {"workKey": key, "tier": "budget", "unit": "m2",
             "scopeId": SCOPE, "source": source, "url": f"https://{source}/priced-work",
             "priceKind": "fixed_price", "priceMDL": amount,
             "verifiedAt": NOW.isoformat(), "priceDateVerified": True,
             "scopeVerified": True}
            for source in ("builder-one.md", "builder-two.md")
        ],
    }
    return catalog, baseline, policy, evidence


class LaborApprovalTests(unittest.TestCase):
    def check_held(self, field, value, *, stage=False):
        catalog, baseline, policy, evidence = fixture(stage=stage)
        original = json.dumps(catalog, sort_keys=True, ensure_ascii=False)
        if field.startswith("policy."):
            policy[field.split(".", 1)[1]] = value
        elif field.startswith("mapping."):
            policy["approvedMappings"][0][field.split(".", 1)[1]] = value
        elif field.startswith("evidence."):
            evidence[field.split(".", 1)[1]] = value
        elif field.startswith("quote2."):
            evidence["quotes"][1][field.split(".", 1)[1]] = value
        else:
            evidence["quotes"][0][field] = value
        result, candidate = plan(catalog, baseline, policy, evidence, now=NOW)
        self.assertEqual(result["proposedCount"], 0)
        self.assertEqual(candidate, catalog)
        self.assertEqual(json.dumps(catalog, sort_keys=True, ensure_ascii=False), original)

    def test_two_dated_fixed_prices_can_be_prepared_but_never_published(self):
        catalog, baseline, policy, evidence = fixture()
        report, candidate = plan(catalog, baseline, policy, evidence, now=NOW)
        self.assertEqual(report["proposedCount"], 1)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["approvedForPublication"])
        self.assertEqual(candidate["laborPrices"]["wallPaintWork"]["budget"], 24)
        self.assertEqual(catalog["laborPrices"]["wallPaintWork"]["budget"], 22.75)
        self.assertEqual(validate(candidate, baseline), [])

    def test_no_policy_consent(self):
        self.check_held("policy.automaticPublicationApproved", False)

    def test_no_manual_scope_approval(self):
        self.check_held("mapping.manuallyApproved", False)

    def test_unverified_work_scope(self):
        self.check_held("scopeVerified", False)

    def test_unit_mismatch(self):
        self.check_held("unit", "piece")

    def test_scope_mismatch(self):
        self.check_held("scopeId", "floor-paint-different-job")

    def test_date_not_verified(self):
        self.check_held("priceDateVerified", False)

    def test_stale_evidence(self):
        self.check_held("evidence.generatedAt", (NOW - timedelta(days=2)).isoformat())

    def test_stale_quote_date(self):
        self.check_held("verifiedAt", (NOW - timedelta(days=2)).isoformat())

    def test_marketing_from_price_not_fixed(self):
        self.check_held("priceKind", "from_price")

    def test_duplicate_store_domain(self):
        self.check_held("quote2.url", "https://builder-one.md/other-work")

    def test_unapproved_source_domain(self):
        self.check_held("quote2.url", "https://unapproved-seller.md/job")

    def test_quote_spread_exceeds_twelve_percent(self):
        self.check_held("quote2.priceMDL", 35)

    def test_price_change_above_eight_percent(self):
        catalog, baseline, policy, evidence = fixture()
        for quote in evidence["quotes"]:
            quote["priceMDL"] = 30
        result, candidate = plan(catalog, baseline, policy, evidence, now=NOW)
        self.assertEqual(result["proposedCount"], 0)
        self.assertEqual(candidate, catalog)

    def test_single_quote_must_not_pass(self):
        self.check_held("evidence.quotes", fixture()[3]["quotes"][:1])

    def test_duplicate_approvals_rejected(self):
        catalog, baseline, policy, evidence = fixture()
        policy["approvedMappings"].append(deepcopy(policy["approvedMappings"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            plan(catalog, baseline, policy, evidence, now=NOW)

    def test_optional_start_putty_staged_in_separate_catalog_group(self):
        catalog, baseline, policy, evidence = fixture(stage=True)
        # 41 -> 41 is below 2%: use 42 instead.
        for quote in evidence["quotes"]:
            quote["priceMDL"] = 42
        result, candidate = plan(catalog, baseline, policy, evidence, now=NOW)
        self.assertEqual(result["proposedCount"], 1)
        self.assertEqual(candidate["laborStagePrices"]["startPuttyWork"]["budget"], 42)
        self.assertEqual(validate(candidate, baseline), [])

    def test_labor_only_release_with_material_policy_disabled(self):
        catalog, baseline, labor_policy, labor_evidence = fixture()
        material_policy = {"schemaVersion": 1, "enabled": False, "approvedMappings": []}
        material_sources = {"country": "MD", "currency": "MDL", "materials": []}
        material_obs = {"country": "MD", "currency": "MDL",
                        "generatedAt": NOW.isoformat(), "materials": []}
        frozen = deepcopy(catalog)
        report, candidate = prepare(
            catalog, baseline, material_sources, material_obs, material_policy,
            now=NOW, labor_policy=labor_policy, labor_evidence=labor_evidence)
        self.assertEqual(report["status"], "ready_for_guarded_publication")
        self.assertEqual(report["proposedPriceChanges"], 1)
        self.assertEqual(report["laborProposedPriceChanges"], 1)
        self.assertEqual(report["catalogVersionCandidate"], "0.1.3")
        self.assertEqual(report["lastVerifiedPartialLaborChangeDate"], "2026-11-05")
        self.assertEqual(candidate["materialPrices"], frozen["materialPrices"])
        self.assertEqual(candidate["laborPrices"]["wallPaintWork"]["budget"], 24)
        self.assertEqual(candidate["sourceAuditDate"], "2026-11-05")
        self.assertEqual(catalog, frozen)
        self.assertEqual(validate(candidate, baseline), [])

    def test_independently_approved_material_and_labor_can_share_one_candidate(self):
        from test_prepare_verified_catalog_release import fixture as material_fixture
        catalog, baseline, sources, observations, material_policy = material_fixture()
        observations["generatedAt"] = NOW.isoformat()
        _unused, _unused, labor_policy, labor_evidence = fixture()
        report, candidate = prepare(
            catalog, baseline, sources, observations, material_policy, now=NOW,
            labor_policy=labor_policy, labor_evidence=labor_evidence)
        self.assertEqual(report["status"], "ready_for_guarded_publication")
        self.assertEqual(report["proposedPriceChanges"], 2)
        self.assertEqual(report["laborProposedPriceChanges"], 1)
        self.assertEqual(candidate["materialPrices"]["gypsumPlaster"]["standard"]["price"], 152)
        self.assertEqual(candidate["laborPrices"]["wallPaintWork"]["budget"], 24)
        self.assertEqual(candidate["sourceAuditDate"], catalog["sourceAuditDate"])
        self.assertEqual(validate(candidate, baseline), [])

    def test_disabling_labor_publication_blocks_release(self):
        catalog, baseline, labor_policy, labor_evidence = fixture()
        labor_policy["automaticPublicationApproved"] = False
        material_policy = {"schemaVersion": 1, "enabled": False, "approvedMappings": []}
        sources = {"country": "MD", "currency": "MDL", "materials": []}
        obs = {"country": "MD", "currency": "MDL",
               "generatedAt": NOW.isoformat(), "materials": []}
        report, candidate = prepare(
            catalog, baseline, sources, obs, material_policy, now=NOW,
            labor_policy=labor_policy, labor_evidence=labor_evidence)
        self.assertIsNone(candidate)
        self.assertEqual(report["status"], "held")

    def test_default_repository_has_no_approved_labor_rate(self):
        catalog = load(ROOT / "published_catalog/prices.json")
        baseline = load(ROOT / "published_catalog/compatibility_baseline.json")
        policy = load(ROOT / "labor_update_policy.json")
        evidence = load(ROOT / "verified_labor_quotes.json")
        result, candidate = plan(catalog, baseline, policy, evidence, now=NOW)
        self.assertEqual(result["proposedCount"], 0)
        self.assertEqual(candidate, catalog)

    def test_publisher_workflow_has_separate_labor_gate(self):
        workflow = (ROOT / ".github/workflows/approved-price-publisher.yml").read_text(
            encoding="utf-8")
        self.assertIn("--labor-policy labor_update_policy.json", workflow)
        self.assertIn("--labor-evidence verified_labor_quotes.json", workflow)
        self.assertIn("labor_policy.get('automaticPublicationApproved') is True", workflow)
        self.assertIn("labor changes without separate labor approval", workflow)
        self.assertNotIn("--labor-evidence live_labor_quotes.json", workflow)


if __name__ == "__main__":
    unittest.main()
