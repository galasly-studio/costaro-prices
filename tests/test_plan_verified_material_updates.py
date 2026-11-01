"""Fail-closed, network-free tests for monthly material price proposals."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from plan_verified_material_updates import plan  # noqa: E402
from validate_app_catalog import load  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def sample():
    catalog = load(ROOT / "prices.json")
    baseline = load(ROOT / "app_embedded_baseline.json")
    source = {
        "id": "checked_25kg_plaster", "catalogMaterialKey": "gypsumPlaster",
        "priceTier": "standard", "unit": "bag", "packageWeightKg": 25,
        "sources": [
            {"store": "Store A", "url": "https://store-a.md/checked-plaster", "productCode": "a-123"},
            {"store": "Store B", "url": "https://store-b.md/checked-plaster", "productCode": "b-123"},
        ],
    }
    sources = {"country": "MD", "currency": "MDL", "materials": [source]}
    observed = {
        "country": "MD", "currency": "MDL", "generatedAt": NOW.isoformat(),
        "materials": [{
            "id": source["id"], "observations": [
                {**item, "status": "candidate", "extractionMethod": "product_microdata", "price": value}
                for item, value in zip(source["sources"], (151, 153))
            ]
        }],
    }
    policy = {
        "schemaVersion": 1, "enabled": True,
        "approvedMappings": [{"observationId": source["id"],
                              "catalogMaterialKey": "gypsumPlaster", "tier": "standard"}],
    }
    return catalog, baseline, sources, observed, policy


class SafeMaterialProposalTests(unittest.TestCase):
    def evaluate(self, sample_data):
        result, candidate = plan(*sample_data, now=NOW)
        self.assertEqual(len(result["materials"]), 1)
        return result["materials"][0], result, candidate

    def test_verified_proposal_does_not_modify_input(self):
        data = sample()
        before = json.dumps(data[0], ensure_ascii=False, sort_keys=True)
        row, report, candidate = self.evaluate(data)
        self.assertEqual(row["status"], "proposed")
        self.assertEqual(row["previousMDL"], 144)
        self.assertEqual(row["proposedMDL"], 152)
        self.assertEqual(candidate["materialPrices"]["gypsumPlaster"]["standard"]["price"], 152)
        self.assertEqual(json.dumps(data[0], ensure_ascii=False, sort_keys=True), before)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["verifiedForPublication"])

    def test_policy_disabled(self):
        data = sample()
        data[4]["enabled"] = False
        row, report, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "automatic_proposals_disabled")
        self.assertEqual(report["proposedCount"], 0)

    def test_missing_approval(self):
        data = sample()
        data[4]["approvedMappings"] = []
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "tier_mapping_not_approved")

    def test_price_tier_missing(self):
        data = sample()
        data[2]["materials"][0]["priceTier"] = None
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "source_has_no_reviewed_price_tier")

    def test_twenty_kg_product_cannot_replace_eight_kg_pack(self):
        data = sample()
        data[2]["materials"][0].update({"catalogMaterialKey": "finishPutty", "packageWeightKg": 20})
        data[4]["approvedMappings"][0]["catalogMaterialKey"] = "finishPutty"
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "source_pack_does_not_match_catalog_pack")

    def test_stale_observations(self):
        data = sample()
        data[3]["generatedAt"] = (NOW - timedelta(days=2)).isoformat()
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "observations_not_fresh")

    def test_future_observations(self):
        data = sample()
        data[3]["generatedAt"] = (NOW + timedelta(hours=1)).isoformat()
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "observations_not_fresh")

    def test_unavailable_source_fail_closed(self):
        data = sample()
        data[3]["materials"][0]["observations"][1]["status"] = "unavailable"
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "store_unavailable_or_ambiguous")

    def test_visible_text_not_trusted_for_auto(self):
        data = sample()
        data[3]["materials"][0]["observations"][0]["extractionMethod"] = "visible_text"
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "product_identity_not_strongly_verified")

    def test_json_ld_not_strong_enough(self):
        data = sample()
        data[3]["materials"][0]["observations"][0]["extractionMethod"] = "structured_data"
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "product_identity_not_strongly_verified")

    def test_fake_or_changed_sku(self):
        data = sample()
        data[3]["materials"][0]["observations"][1]["productCode"] = "wrong"
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "observation_does_not_match_source")

    def test_same_store_cannot_vote_twice(self):
        data = sample()
        data[2]["materials"][0]["sources"][1]["store"] = "Store A"
        data[3]["materials"][0]["observations"][1]["store"] = "Store A"
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "shops_not_independent")

    def test_same_domain_cannot_vote_twice(self):
        data = sample()
        url = "https://store-a.md/other-product"
        data[2]["materials"][0]["sources"][1]["url"] = url
        data[3]["materials"][0]["observations"][1]["url"] = url
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "shops_not_independent")

    def test_price_spread_exceeds_twelve_percent(self):
        data = sample()
        data[3]["materials"][0]["observations"][0]["price"] = 120
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "independent_store_prices_disagree")

    def test_large_monthly_change_rejected(self):
        data = sample()
        data[3]["materials"][0]["observations"][0]["price"] = 160
        data[3]["materials"][0]["observations"][1]["price"] = 162
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "price_change_above_eight_percent")

    def test_tiny_change_not_published(self):
        data = sample()
        data[3]["materials"][0]["observations"][0]["price"] = 145
        data[3]["materials"][0]["observations"][1]["price"] = 146
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "price_change_below_two_percent")

    def test_tier_order_protection(self):
        data = sample()
        # The reference catalog may only be modified in budget/standard/premium order.
        data[0]["materialPrices"]["gypsumPlaster"]["premium"]["price"] = 148
        row, _, _ = self.evaluate(data)
        self.assertEqual(row["reason"], "complete_catalog_validation_failed")

    def test_invalid_policy_fails_loudly(self):
        data = sample()
        data[4]["enabled"] = "true"
        with self.assertRaisesRegex(ValueError, "boolean"):
            plan(*data, now=NOW)

    def test_duplicate_approval_fails_loudly(self):
        data = sample()
        data[4]["approvedMappings"].append(deepcopy(data[4]["approvedMappings"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            plan(*data, now=NOW)

    def test_two_product_ids_cannot_assign_the_same_catalog_tier(self):
        data = sample()
        extra = deepcopy(data[4]["approvedMappings"][0])
        extra["observationId"] = "other_product_id"
        data[4]["approvedMappings"].append(extra)
        with self.assertRaisesRegex(ValueError, "Duplicate approved catalog material/tier"):
            plan(*data, now=NOW)

    def test_unknown_approved_id_rejected(self):
        data = sample()
        data[4]["approvedMappings"][0]["observationId"] = "wrong-id"
        with self.assertRaisesRegex(ValueError, "unknown observationId"):
            plan(*data, now=NOW)

    def test_real_repository_starts_with_no_approved_updates(self):
        catalog = load(ROOT / "prices.json")
        baseline = load(ROOT / "app_embedded_baseline.json")
        sources = load(ROOT / "price_sources.json")
        policy = load(ROOT / "material_update_policy.json")
        simulated = {"country": "MD", "currency": "MDL", "generatedAt": NOW.isoformat(),
                     "materials": [{"id": row["id"], "observations": []}
                                   for row in sources["materials"]]}
        report, candidate = plan(catalog, baseline, sources, simulated, policy, now=NOW)
        self.assertEqual(report["proposedCount"], 0)
        self.assertEqual(candidate, catalog)


if __name__ == "__main__":
    unittest.main()
