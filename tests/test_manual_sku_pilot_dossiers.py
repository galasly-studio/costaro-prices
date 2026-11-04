import copy
import json
import unittest
from pathlib import Path

from scripts import build_manual_sku_pilot_dossiers as stage


def fixtures():
    root = Path(__file__).resolve().parents[1]
    catalog = json.loads((root / "prices.json").read_text(encoding="utf-8"))
    retail = json.loads((root / "price_sources.json").read_text(encoding="utf-8"))
    policy = json.loads((root / "material_update_policy.json").read_text(encoding="utf-8"))
    keys = sorted(catalog["materialPrices"])
    by_key = {}
    for group in retail["materials"]:
        if len(group["sources"]) >= 2:
            by_key.setdefault(group["catalogMaterialKey"], group)
    candidates = list(stage.PILOT_KEYS) + [k for k in keys if k not in stage.PILOT_KEYS and k in by_key][:18]
    assert len(candidates) == 23
    safe = {flag: False for flag in stage.SAFE_FLAGS}
    bulk_rows = []
    docs = []
    for key in candidates:
        source_pair = by_key[key]["sources"][:2]
        retail_sources = [
            {"store": s["store"], "url": s["url"], "productCode": s["productCode"],
             "extractionMethod": "product_structured_sku",
             "displayedPriceMDLResearchOnly": 100.0}
            for s in source_pair
        ]
        bulk_rows.append({
            "catalogMaterialKey": key, "configuredProductName": key,
            "twoRetailSitesConfirmedInConfiguration": True,
            "configuredStoreAndCodeTraceConsistent": True, "httpsSourceUrls": True,
            "researchSourceIdentityConsistent": True, "retailSources": retail_sources,
            "technicalFamilyId": "test_family",
            "technicalRequirements": [{"criterionRu": "Сверить применение", "objectiveEvidenceVerified": False}],
            "manufacturerModelMatchIndependentlyVerified": False,
            "moldovaPhysicalStockVerified": False,
            "currentPriceDateIndependentlyVerified": False,
            "qualityTierApproved": False, "approvedForPublication": False,
        })
        docs.append({
            "catalogMaterialKey": key,
            "configuredProductName": key,
            "officialSourceLeadUrl": "https://manufacturer.example/product",
            "contentReadStatus": "text_extracted_html",
            "contentSha256": "digest",
            "companyContentEvidence": {
                "modelFamilyMarkersPresent": True,
                "configuredPackageOrRatingMentioned": candidates.index(key) < 11,
                "technicalRestrictionSignals": [],
            },
            "approvedQualityTier": None, "approvedPriceChange": False,
        })
    bulk = dict(safe, candidates=bulk_rows)
    manufacturer = dict(safe, records=docs)
    matrix = dict(safe, materials=[
        {"catalogMaterialKey": key, "approvedForPublication": False}
        for key in keys
    ])
    readiness = {"status": "held", "policyEnabled": False,
                 "explicitPublicationApproved": False,
                 "approvedMappingCount": 0, "proposedPriceChanges": 0}
    market_audit = {"status": "audit_only", "summary": {"verifiedForPublication": 0}}
    return dict(catalog=catalog, retail=retail, bulk=bulk, manufacturer=manufacturer,
                matrix=matrix, readiness=readiness, policy=policy, market_audit=market_audit)


class Stage47Tests(unittest.TestCase):
    def test_full_pilot_is_research_only_and_unapproved(self):
        report = stage.build(**fixtures())
        self.assertEqual(report["summary"]["catalogMaterials"], 41)
        self.assertEqual(report["summary"]["strictResearchProductGroups"], 23)
        self.assertEqual(report["summary"]["technicalAndSourceConsistentResearchLeadsNotApproved"], 11)
        self.assertEqual(report["summary"]["firstHumanPilotDossiers"], 5)
        self.assertEqual(report["summary"]["approvedTierMappings"], 0)
        self.assertFalse(report["automaticPublicationEnabled"])
        for row in report["allResearchLeads"]:
            self.assertFalse(row["productExactSkuIndependentlyVerified"])
            self.assertFalse(row["priceDateIndependentlyVerified"])
            self.assertFalse(row["budgetStandardPremiumMappingApproved"])
            self.assertFalse(row["approvedPriceChange"])
            self.assertIsNone(row["approvedTier"])
            self.assertEqual(len(row["retailResearchNotForCatalog"]), 2)

    def test_no_price_or_policy_mutation(self):
        inputs = fixtures()
        snapshot = copy.deepcopy(inputs)
        stage.build(**inputs)
        self.assertEqual(inputs, snapshot)

    def test_missing_pilot_company_pack_disallows_pilot(self):
        inputs = fixtures()
        row = next(x for x in inputs["manufacturer"]["records"]
                   if x["catalogMaterialKey"] == stage.PILOT_KEYS[0])
        row["companyContentEvidence"]["configuredPackageOrRatingMentioned"] = False
        with self.assertRaises(ValueError):
            stage.build(**inputs)

    def test_source_must_be_traced_to_exact_configured_listing(self):
        inputs = fixtures()
        row = next(x for x in inputs["bulk"]["candidates"]
                   if x["catalogMaterialKey"] == stage.PILOT_KEYS[0])
        row["retailSources"][0]["url"] = "https://other.example/product"
        with self.assertRaises(ValueError):
            stage.build(**inputs)

    def test_preapproval_flags_or_policy_changes_are_refused(self):
        for source, path, value in (
            ("policy", "enabled", True),
            ("catalog", "automaticUpdatesEnabled", True),
            ("readiness", "status", "ready"),
        ):
            with self.subTest(field=path):
                inputs = fixtures()
                inputs[source][path] = value
                with self.assertRaises(ValueError):
                    stage.build(**inputs)


if __name__ == "__main__":
    unittest.main()
