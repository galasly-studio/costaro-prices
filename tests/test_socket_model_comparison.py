import copy
import json
import unittest
from pathlib import Path

from scripts import build_socket_model_comparison as stage
from scripts import build_manual_sku_pilot_dossiers as stage47
from tests.test_manual_sku_pilot_dossiers import fixtures as stage47_fixtures


ROOT = Path(__file__).resolve().parents[1]


def fixture():
    # GitHub Actions executes unittest *before* the Stage47 report is generated.
    # Reuse Stage47's synthetic source fixtures, so tests require no CI artifacts.
    source_inputs = stage47_fixtures()
    research = json.loads((ROOT / "socket_comparison_research_sources.json").read_text(encoding="utf-8"))
    official_asfora = research["models"][0]["officialUrl"]
    for item in source_inputs["manufacturer"]["records"]:
        if item["catalogMaterialKey"] == "electricalSocketPerPiece":
            item["officialSourceLeadUrl"] = official_asfora
    return {
        "pilot": stage47.build(**source_inputs),
        "research": research,
        "catalog": source_inputs["catalog"],
        "policy": source_inputs["policy"],
        "readiness": source_inputs["readiness"],
    }


class Stage48Tests(unittest.TestCase):
    def test_four_models_researched_with_no_preapproved_quality_tiers(self):
        output = stage.build(**fixture())
        self.assertEqual(output["status"], "socket_quality_comparison_research_only")
        s = output["summary"]
        self.assertEqual(s["catalogMaterialsUntouched"], 41)
        self.assertEqual(s["manufacturerPartNumbersCompared"], 4)
        self.assertEqual(s["modelsWithTwoMoldovaRetailSiteLeads"], 3)
        self.assertEqual(s["modelsWithTwoExactRetailProductPageLeads"], 2)
        self.assertEqual(s["modelsBlockedByStatusOrConflictingDescriptions"], 1)
        self.assertEqual(s["modelsEligibleForNextHumanDocumentReviewOnly"], 1)
        self.assertEqual(s["independentlyApprovedQualityTiers"], 0)
        self.assertEqual(s["verifiedLivePriceChanges"], 0)
        for field in stage.SAFE_FLAGS:
            self.assertFalse(output[field], field)
        for row in output["models"]:
            self.assertIsNone(row["approvedTier"])
            self.assertFalse(row["approvedPriceChange"])
            self.assertFalse(row["autoPublicationAllowed"])
            self.assertFalse(row["moldovaPhysicalStockAndPriceDateVerified"])
            self.assertFalse(row["independentTechnicalPerformanceTestVerified"])

    def test_asfora_only_reaches_manual_document_review(self):
        output = stage.build(**fixture())
        routes = {x["mpn"]: x["reviewRoute"] for x in output["models"]}
        self.assertEqual(routes["EPH2900221"], "candidate_for_human_document_review_only")
        self.assertEqual(routes["LMR5210001"], "second_exact_retail_product_card_required")
        self.assertEqual(routes["NU303718"], "second_moldova_store_required")
        self.assertEqual(routes["GSL000145"],
                         "blocked_pending_product_status_and_specification_recheck")

    def test_discontinued_notice_and_merchant_discrepancy_block_glossa(self):
        x = next(row for row in stage.build(**fixture())["models"]
                 if row["mpn"] == "GSL000145")
        self.assertIn("manufacturer_regional_discontinuation_notice", x["researchFlags"])
        self.assertIn("retailer_grounding_or_frame_description_conflict", x["researchFlags"])

    def test_source_changes_cannot_turn_on_publication(self):
        for source, key, value in (
            ("policy", "enabled", True),
            ("catalog", "automaticUpdatesEnabled", True),
            ("readiness", "explicitPublicationApproved", True),
            ("pilot", "automaticTierAssignmentEnabled", True),
        ):
            with self.subTest(field=key):
                data = fixture()
                data[source][key] = value
                with self.assertRaises(ValueError):
                    stage.build(**data)

    def test_no_in_memory_source_or_catalog_change(self):
        data = fixture()
        prior = copy.deepcopy(data)
        stage.build(**data)
        self.assertEqual(data, prior)

    def test_different_manufacturer_part_code_is_rejected(self):
        data = fixture()
        data["research"]["models"][1]["officialUrl"] = data["research"]["models"][0]["officialUrl"]
        with self.assertRaisesRegex(ValueError, "wrong part number"):
            stage.build(**data)

    def test_asfora_manufacturer_link_must_match_previous_stage(self):
        data = fixture()
        data["research"]["models"][0]["officialUrl"] = (
            "https://www.se.com/kz/ru/product/EPH2900221/another-page/"
        )
        with self.assertRaisesRegex(ValueError, "Stage47 anchor"):
            stage.build(**data)

    def test_store_listing_must_show_exact_matching_model_code(self):
        data = fixture()
        data["research"]["models"][0]["retailLeads"][1]["codeShown"] = "EPH2900121"
        with self.assertRaises(ValueError):
            stage.build(**data)

    def test_store_domain_mismatch_is_rejected(self):
        data = fixture()
        data["research"]["models"][0]["retailLeads"][0]["url"] = "https://evil.example/EPH2900221"
        with self.assertRaises(ValueError):
            stage.build(**data)

    def test_discontinuation_notice_cannot_be_silently_removed(self):
        data = fixture()
        data["research"]["models"][2]["manufacturerLifecycleSignal"] = "still_produced"
        with self.assertRaises(ValueError):
            stage.build(**data)

    def test_source_description_conflict_remains_blocked_if_discontinuation_not_known(self):
        data = fixture()
        data["research"]["models"][2]["manufacturerLifecycleSignal"] = \
            "no_discontinuation_notice_in_reviewed_page"
        output = stage.build(**data)
        glossa = next(x for x in output["models"] if x["mpn"] == "GSL000145")
        self.assertTrue(glossa["reviewRoute"].startswith("blocked"))

    def test_price_snapshot_is_not_quality_ranking(self):
        data = fixture()
        data["research"]["models"][0]["retailLeads"][0]["priceSnapshotMDLNotVerified"] = 10000
        output = stage.build(**data)
        self.assertEqual(output["summary"]["independentlyApprovedQualityTiers"], 0)
        self.assertIsNone(output["models"][0]["approvedTier"])


if __name__ == "__main__":
    unittest.main()
