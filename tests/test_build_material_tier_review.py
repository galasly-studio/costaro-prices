"""Network-free safety regression tests for human-only tier review outputs."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_material_tier_review import build, summary_markdown  # noqa: E402
from validate_app_catalog import load  # noqa: E402


NOW = datetime(2026, 11, 1, 13, tzinfo=timezone.utc)


def fixture():
    catalog = load(ROOT / "prices.json")
    baseline = load(ROOT / "app_embedded_baseline.json")
    sources = load(ROOT / "price_sources.json")
    policy = load(ROOT / "material_update_policy.json")
    observation_rows, audit_rows = [], []
    for product in sources["materials"]:
        hint = product.get("tierCandidateForReview")
        key = product["catalogMaterialKey"]
        catalog_tier = catalog["materialPrices"].get(key, {}).get(hint) if hint else None
        p = catalog_tier.get("price", 100) if isinstance(catalog_tier, dict) else 100
        records = [{**shop, "status": "candidate", "price": float(p),
                    "extractionMethod": "structured_data"}
                   for shop in product["sources"]]
        observation_rows.append({"id": product["id"], "observations": records})
        audit_rows.append({"id": product["id"], "catalogMaterialKey": key,
                           "candidateMedianMDL": float(p) if records else None,
                           "comparisonReady": len(records) > 1})
    observations = {"country": "MD", "currency": "MDL",
                    "generatedAt": NOW.isoformat(), "materials": observation_rows}
    audit = {"country": "MD", "currency": "MDL", "status": "audit_only",
             "materials": audit_rows}
    return [catalog, baseline, sources, observations, audit, policy]


class HumanTierReviewTests(unittest.TestCase):
    def evaluate(self, f):
        return build(*f, now=NOW)

    def test_51_groups_but_only_six_human_tier_candidates(self):
        f = fixture()
        catalog_before = json.dumps(f[0], ensure_ascii=False, sort_keys=True)
        output = self.evaluate(f)
        self.assertEqual(output["summary"], {
            "catalogMaterialCount": 41,
            "productGroupCount": 51,
            "reviewCandidates": 6,
            "materialsWithCompleteThreeTierCandidateSet": 2,
            "heldProductGroups": 45,
        })
        self.assertEqual(output["status"], "human_review_only")
        self.assertEqual(output["approvedTierMappings"], 0)
        self.assertFalse(output["automaticPublicationEnabled"])
        self.assertFalse(output["pricesChanged"])
        self.assertEqual(json.dumps(f[0], ensure_ascii=False, sort_keys=True), catalog_before)
        for product in output["products"]:
            self.assertFalse(product["tierQualityReviewed"])
            self.assertFalse(product["approvedForPublication"])
        self.assertIn("Только исследование", summary_markdown(output))

    def test_exact_budget_standard_premium_options_are_not_auto_approved(self):
        output = self.evaluate(fixture())
        by_material = {m["catalogMaterialKey"]: m for m in output["catalogMaterials"]}
        expected = {
            "finishPutty": {
                "budget": "glet_mesterul_manole_8kg",
                "standard": "glet_b62_satroc_8kg",
                "premium": "glet_satroc_8kg",
            },
            "interiorPaint": {
                "budget": "romanita_7kg",
                "standard": "euroton_lav_7kg",
                "premium": "sansiro_7kg",
            },
        }
        for material, tier_ids in expected.items():
            self.assertTrue(by_material[material]["hasCompleteReviewCandidateSet"])
            for tier, product_id in tier_ids.items():
                self.assertEqual(by_material[material]["tiers"][tier]["reviewCandidateIDs"],
                                 [product_id])
        self.assertTrue(all(not m["approvedForPublication"]
                            for m in output["catalogMaterials"]))

    def test_stale_and_future_observations_remove_every_candidate(self):
        for age in (-timedelta(days=2), timedelta(hours=1)):
            f = fixture()
            f[3]["generatedAt"] = (NOW + age).isoformat()
            output = self.evaluate(f)
            self.assertEqual(output["summary"]["reviewCandidates"], 0)
            self.assertFalse(output["observationsFresh"])

    def test_changed_sku_and_price_spread_are_held(self):
        for corruption, expected_reason in (
            ("sku", "observation_source_mismatch"),
            ("spread", "store_price_spread_exceeds_twenty_percent"),
            ("audit", "audit_median_does_not_match_observations"),
            ("missing_shop", "source_observation_count_mismatch"),
        ):
            f = fixture()
            row = next(r for r in f[3]["materials"]
                       if r["id"] == "glet_mesterul_manole_8kg")
            audit_row = next(r for r in f[4]["materials"]
                             if r["id"] == "glet_mesterul_manole_8kg")
            if corruption == "sku":
                row["observations"][1]["productCode"] = "false-code"
            elif corruption == "spread":
                row["observations"][1]["price"] = 999
            elif corruption == "audit":
                audit_row["candidateMedianMDL"] += 7
            else:
                row["observations"].pop()
            result = self.evaluate(f)
            product = next(p for p in result["products"]
                           if p["id"] == "glet_mesterul_manole_8kg")
            self.assertEqual(product["status"], "held")
            self.assertEqual(product["reason"], expected_reason)
            self.assertEqual(result["summary"]["reviewCandidates"], 5)
            self.assertEqual(result["summary"]["materialsWithCompleteThreeTierCandidateSet"], 1)

    def test_wrong_pack_or_unreviewed_tier_does_not_leak_into_queue(self):
        f = fixture()
        product = next(p for p in f[2]["materials"]
                       if p["id"] == "glet_mesterul_manole_8kg")
        product["packageWeightKg"] = 20
        output = self.evaluate(f)
        match = next(p for p in output["products"] if p["id"] == product["id"])
        self.assertEqual(match["reason"], "retail_pack_does_not_match_catalog_tier")

    def test_missing_quality_hint_never_inferred_from_cheap_price(self):
        f = fixture()
        for row in f[2]["materials"]:
            row.pop("tierCandidateForReview", None)
        output = self.evaluate(f)
        self.assertEqual(output["summary"]["reviewCandidates"], 0)
        self.assertEqual(output["summary"]["materialsWithCompleteThreeTierCandidateSet"], 0)

    def test_disabled_policy_and_clean_ids_are_mandatory(self):
        f = fixture()
        f[5]["enabled"] = True
        with self.assertRaisesRegex(ValueError, "disabled policy"):
            self.evaluate(f)
        f = fixture()
        f[3]["materials"].append(deepcopy(f[3]["materials"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate ID"):
            self.evaluate(f)

    def test_strong_method_does_not_automatically_approve_quality(self):
        f = fixture()
        for row in f[3]["materials"]:
            for entry in row["observations"]:
                entry["extractionMethod"] = "product_microdata"
        out = self.evaluate(f)
        self.assertEqual(out["summary"]["reviewCandidates"], 6)
        self.assertFalse(any(r["approvedForPublication"] for r in out["products"]))
        self.assertFalse(any(r["tierQualityReviewed"] for r in out["products"]))

    def test_monthly_workflow_uploads_both_review_files_without_push(self):
        workflow = (ROOT / ".github/workflows/monthly-price-audit.yml").read_text(
            encoding="utf-8")
        self.assertIn("python3 scripts/build_material_tier_review.py", workflow)
        self.assertIn("material_tier_review.json", workflow)
        self.assertIn("material_tier_review_RU.md", workflow)
        self.assertIn("contents: read", workflow)
        self.assertNotIn("git push", workflow)


if __name__ == "__main__":
    unittest.main()
