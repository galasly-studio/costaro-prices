import copy
import json
import unittest
from pathlib import Path

from scripts import build_material_decision_matrix as stage45
from scripts import build_room_use_guard_review as stage46


def fixtures():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "prices.json").read_text(encoding="utf-8"))
    retailer_sources = json.loads((root / "price_sources.json").read_text(encoding="utf-8"))
    policy = json.loads((root / "material_update_policy.json").read_text(encoding="utf-8"))
    keys = sorted(catalog["materialPrices"])
    mandatory = ["gypsumBoardCeiling", "interiorPaint", "floorScreedMix"]
    candidates = mandatory + [k for k in keys if k not in mandatory][:20]
    safe = {k: False for k in stage45.SAFETY_FLAGS}
    criteria = dict(safe, summary={"catalogMaterials": 41}, allMaterialProfiles=[
        {"catalogMaterialKey": key, "technicalFamilyId": "test_family",
         "qualityTierApproved": False, "approvedForPublication": False,
         "technicalCriteria": [{"criterionRu": "Сфера применения", "independentlyVerified": False}]}
        for key in keys
    ])
    research = dict(safe, summary={"approvedPriceChanges": 0},
                    unmonitoredMaterialKeys=[stage46.COMPOSITE_KEY], candidates=[
        {"catalogMaterialKey": key, "configuredProductName": key,
         "qualityTierApproved": False, "approvedForPublication": False}
        for key in candidates
    ])
    signals = {
        "gypsumBoardCeiling": "technogips_type_a_normal_humidity_room_review",
        "interiorPaint": "company_text_limits_product_to_dry_rooms",
        "floorScreedMix": "regional_thickness_range_disagreement_10_60_vs_25_80",
    }
    content = dict(safe, summary={"approvedQualityTiers": 0}, records=[
        {"catalogMaterialKey": key, "configuredProductName": key,
         "officialSourceLeadUrl": "https://official.example/source",
         "contentReadStatus": "text_extracted_html",
         "approvedQualityTier": None, "approvedPriceChange": False,
         "companyContentEvidence": {
             "modelFamilyMarkersPresent": True,
             "configuredPackageOrRatingMentioned": key != "gypsumBoardCeiling",
             "technicalRestrictionSignals": [signals[key]] if key in signals else [],
         }} for key in candidates
    ])
    readiness = {"status": "held", "policyEnabled": False,
                 "explicitPublicationApproved": False,
                 "approvedMappingCount": 0, "proposedPriceChanges": 0}
    matrix = stage45.build(catalog, retailer_sources, criteria, research, content, readiness, policy)
    return dict(matrix=matrix, content=content, catalog=catalog, retailer_sources=retailer_sources)


class Stage46Tests(unittest.TestCase):
    def test_room_and_composite_guards_are_never_automatic_approvals(self):
        report = stage46.build(**fixtures())
        self.assertEqual(report["summary"]["catalogMaterials"], 41)
        self.assertEqual(report["summary"]["technicalRestrictionsRequiringHumanReview"], 3)
        self.assertEqual(report["summary"]["manufacturerFormatTextGaps"], 1)
        self.assertEqual(report["summary"]["compositePriceItemsWithoutDirectRetailSources"], 1)
        self.assertEqual(report["summary"]["approvedForPublication"], 0)
        self.assertFalse(report["automaticPublicationEnabled"])
        self.assertFalse(report["compositePricingReview"]["normalizationOrAutoUpdateAllowed"])
        self.assertEqual(len({w["catalogMaterialKey"] for w in report["roomUseWarnings"]}), 3)

    def test_report_does_not_mutate_catalog_or_source_evidence(self):
        inputs = fixtures()
        snapshot = copy.deepcopy(inputs)
        stage46.build(**inputs)
        self.assertEqual(inputs, snapshot)

    def test_unknown_restriction_must_not_be_silently_accepted(self):
        inputs = fixtures()
        content_item = next(x for x in inputs["content"]["records"] if x["catalogMaterialKey"] == "interiorPaint")
        matrix_item = next(x for x in inputs["matrix"]["materials"] if x["catalogMaterialKey"] == "interiorPaint")
        content_item["companyContentEvidence"]["technicalRestrictionSignals"] = ["unrecognized_humidity_risk"]
        matrix_item["technicalRestrictionSignals"] = ["unrecognized_humidity_risk"]
        with self.assertRaises(ValueError):
            stage46.build(**inputs)

    def test_composite_fails_if_retail_source_state_changes(self):
        inputs = fixtures()
        item = next(x for x in inputs["retailer_sources"]["materials"]
                    if x["catalogMaterialKey"] == stage46.COMPOSITE_KEY)
        item["sources"].append({"store": "unknown", "url": "https://example.invalid"})
        with self.assertRaises(ValueError):
            stage46.build(**inputs)

    def test_any_approved_tier_or_publication_is_rejected(self):
        inputs = fixtures()
        inputs["matrix"]["materials"][0]["approvedForPublication"] = True
        with self.assertRaises(ValueError):
            stage46.build(**inputs)


if __name__ == "__main__":
    unittest.main()
