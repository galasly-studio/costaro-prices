import copy
import json
import unittest
from pathlib import Path

from scripts import build_socket_document_identity_review as stage
from scripts import build_socket_model_comparison as stage48
from tests.test_socket_model_comparison import fixture as stage48_fixture


ROOT = Path(__file__).resolve().parents[1]


def inputs():
    source = stage48_fixture()
    return {
        "stage48": stage48.build(**source),
        "research": json.loads((ROOT / "socket_asfora_document_leads.json").read_text(encoding="utf-8")),
        "catalog": source["catalog"],
        "policy": source["policy"],
        "readiness": source["readiness"],
    }


class Stage49Tests(unittest.TestCase):
    def test_one_exact_model_still_no_approved_document_or_tier(self):
        report = stage.build(**inputs())
        s = report["summary"]
        self.assertEqual(report["status"], "asfora_exact_document_review_with_unresolved_provenance")
        self.assertEqual(report["mpn"], "EPH2900221")
        self.assertEqual(s["catalogMaterialsUntouched"], 41)
        self.assertEqual(s["socketModelsComparedPreviousStage"], 4)
        self.assertEqual(s["socketSkuDocumentAuditCases"], 1)
        self.assertEqual(s["matchingOfficialManufacturerProductPagesResearchOnly"], 1)
        self.assertEqual(s["manufacturerBrandedDatasheetMirrorsUnverified"], 1)
        self.assertEqual(s["complianceDocumentRetrievalIdentityConflicts"], 1)
        self.assertEqual(s["independentReliabilityLabTestsVerified"], 0)
        self.assertEqual(s["acceptedExactManufacturerDatasheets"], 0)
        self.assertEqual(s["approvedQualityTierMappings"], 0)
        self.assertEqual(s["approvedPriceChanges"], 0)
        self.assertIsNone(report["independentlyCertifiedQualityTier"])
        self.assertFalse(report["approvedPriceChange"])
        self.assertFalse(report["autoPublicationAllowed"])
        for flag in stage.SAFE_FLAGS:
            self.assertFalse(report[flag])

    def test_different_product_pdf_is_rejected_for_this_sku(self):
        result = stage.build(**inputs())
        self.assertEqual(result["complianceLinkRetrieval"]["observedOtherMpn"], "A9CR5263")
        self.assertTrue(result["complianceLinkRetrieval"]["documentRejectedForProductApproval"])

    def test_never_mutates_input_sources_or_price_policy(self):
        source = inputs()
        before = copy.deepcopy(source)
        stage.build(**source)
        self.assertEqual(source, before)

    def test_wrong_manufacturer_url_disallows_reconciliation(self):
        source = inputs()
        source["research"]["officialManufacturerProductPage"]["url"] = (
            "https://www.se.com/ro/ro/product/LMR5210001/other/"
        )
        with self.assertRaises(ValueError):
            stage.build(**source)

    def test_mirror_must_not_be_pretended_official(self):
        source = inputs()
        source["research"]["manufacturerBrandedDatasheetMirror"]["hostIsManufacturerControlled"] = True
        with self.assertRaises(ValueError):
            stage.build(**source)

    def test_conflicting_retrieved_document_must_never_be_approved(self):
        source = inputs()
        source["research"]["officialComplianceDocumentRetrievalLead"]["acceptedAsThisProductComplianceEvidence"] = True
        with self.assertRaises(ValueError):
            stage.build(**source)

    def test_no_allowance_for_wet_room_ip44_without_document(self):
        source = inputs()
        source["research"]["manufacturerBrandedDatasheetMirror"]["observedIpClass"] = "IP44"
        with self.assertRaises(ValueError):
            stage.build(**source)

    def test_stage48_tier_assignment_must_remain_blocked(self):
        source = inputs()
        source["stage48"]["models"][0]["approvedTier"] = "premium"
        with self.assertRaises(ValueError):
            stage.build(**source)

    def test_policy_approval_change_aborts_stage(self):
        source = inputs()
        source["policy"]["enabled"] = True
        with self.assertRaises(ValueError):
            stage.build(**source)


if __name__ == "__main__":
    unittest.main()
