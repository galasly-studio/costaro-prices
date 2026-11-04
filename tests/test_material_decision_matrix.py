import copy
import unittest
from pathlib import Path
import json

from scripts import build_material_decision_matrix as stage


def fixture():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "prices.json").read_text(encoding="utf-8"))
    sources = json.loads((root / "price_sources.json").read_text(encoding="utf-8"))
    policy = json.loads((root / "material_update_policy.json").read_text(encoding="utf-8"))
    keys = sorted(catalog["materialPrices"])
    candidate_keys = keys[:23]
    safe = {flag: False for flag in stage.SAFETY_FLAGS}
    criteria = dict(safe, summary={"catalogMaterials": 41}, allMaterialProfiles=[
        {"catalogMaterialKey": key, "technicalFamilyId": "test_family",
         "qualityTierApproved": False, "approvedForPublication": False,
         "technicalCriteria": [{"criterionRu": "Тип товара", "independentlyVerified": False}]}
        for key in keys
    ])
    research = dict(safe, summary={"approvedPriceChanges": 0},
                    unmonitoredMaterialKeys=[candidate_keys[0]], candidates=[
        {"catalogMaterialKey": key, "configuredProductName": key,
         "qualityTierApproved": False, "approvedForPublication": False}
        for key in candidate_keys
    ])
    content = dict(safe, summary={"approvedQualityTiers": 0}, records=[
        {"catalogMaterialKey": key, "officialSourceLeadUrl": "https://official.example/test"
         if i < 14 else None, "contentReadStatus": "text_extracted_pdf" if i < 14 else
         "official_source_not_identified", "approvedQualityTier": None,
         "approvedPriceChange": False,
         "companyContentEvidence": {
             "modelFamilyMarkersPresent": True,
             "configuredPackageOrRatingMentioned": i < 11,
             "technicalRestrictionSignals": ["company_text_limits_product_to_dry_rooms"]
             if i == 2 else []}}
        for i, key in enumerate(candidate_keys)
    ])
    readiness = {"status": "held", "policyEnabled": False,
                 "explicitPublicationApproved": False,
                 "approvedMappingCount": 0, "proposedPriceChanges": 0}
    return dict(catalog=catalog, configured=sources, criteria=criteria,
                research=research, content=content, readiness=readiness, policy=policy)


class Stage45Tests(unittest.TestCase):
    def test_full_41_matrix_and_priorities_never_approve(self):
        report = stage.build(**fixture())
        summary = report["summary"]
        self.assertEqual(summary["catalogMaterials"], 41)
        self.assertEqual(summary["strictTwoStoreResearchCandidatesNotApproved"], 23)
        self.assertEqual(summary["withoutStrictTwoStoreResearchCandidates"], 18)
        self.assertEqual(summary["officialCompanyDocumentLeads"], 14)
        self.assertEqual(summary["companyTextMissingConfiguredFormat"], 3)
        self.assertEqual(summary["criticalTechnicalConflictMaterials"], 1)
        self.assertEqual(summary["withoutLivePriceObservations"], 1)
        self.assertEqual(summary["approvedQualityTiers"], 0)
        self.assertEqual(summary["approvedPriceChanges"], 0)
        self.assertFalse(report["automaticPublicationEnabled"])
        for row in report["materials"]:
            self.assertFalse(row["exactRetailSkuIndependentlyVerified"])
            self.assertFalse(row["approvedForPublication"])
            self.assertTrue(row["manualReviewRequired"])
            self.assertIsNone(row["approvedQualityTier"])
            self.assertTrue(row["nextRequiredActionsRu"])

    def test_never_mutates_catalog_or_sources(self):
        original = fixture()
        frozen = copy.deepcopy(original)
        stage.build(**original)
        self.assertEqual(original, frozen)

    def test_rejects_auto_publication_and_tier_mapping(self):
        for field, change in (("policy", lambda x: x.update(enabled=True)),
                              ("policy", lambda x: x.update(approvedMappings=[{}])),
                              ("readiness", lambda x: x.update(status="ready")),
                              ("research", lambda x: x.update(approvedPriceChanges=True)),
                              ("catalog", lambda x: x.update(automaticUpdatesEnabled=True))):
            with self.subTest(field=field, change=change):
                data = fixture()
                change(data[field])
                with self.assertRaises(ValueError):
                    stage.build(**data)

    def test_detects_duplicate_research_or_missing_technical_profile(self):
        data = fixture()
        data["research"]["candidates"].append(data["research"]["candidates"][0])
        with self.assertRaises(ValueError):
            stage.build(**data)
        data = fixture()
        data["criteria"]["allMaterialProfiles"].pop()
        with self.assertRaises(ValueError):
            stage.build(**data)

    def test_conflict_has_priority_before_other_research(self):
        report = stage.build(**fixture())
        critical = [r for r in report["materials"] if r["technicalRestrictionSignals"]]
        self.assertEqual(len(critical), 1)
        self.assertEqual(critical[0]["priority"], 1)
        self.assertIn("technical_conflict", critical[0]["priorityReason"])


if __name__ == "__main__":
    unittest.main()
