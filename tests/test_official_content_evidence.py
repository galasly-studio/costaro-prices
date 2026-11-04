import unittest

from scripts import build_official_content_evidence as stage


MISSING = (
    "ceilingCdProfile", "ceilingDirectHangerPerPiece",
    "ceilingExtensionConnectorPerPiece", "ceilingUdProfile",
    "ceilingJointTape", "ceilingMetalScrews",
    "electricalLightingCablePerM", "electricalSocketCablePerM",
    "electricalSwitchPerPiece",
)


def fixtures():
    keys = list(stage.OFFICIAL) + list(MISSING)
    safe = {
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
    }
    stage42 = dict(safe, candidates=[
        {
            "catalogMaterialKey": key,
            "configuredProductName": "Sapa Kreisel 441 (10-60mm), 25kg"
            if key == "floorScreedMix" else key,
        } for key in keys
    ])
    stage43 = dict(safe, records=[
        {
            "catalogMaterialKey": key,
            "officialSourceLeadUrl": stage.OFFICIAL[key][0] if key in stage.OFFICIAL else None,
            "manualReviewNoteRu": "Проверить вручную",
        } for key in keys
    ])
    return stage42, stage43


class Stage44Tests(unittest.TestCase):
    def test_content_report_stays_unapproved_for_all_23(self):
        data42, data43 = fixtures()
        report = stage.audit(data42, data43, fetch=lambda _: {
            "status": "text_extracted_html",
            "text": "Unknown item, other product family",
            "sha256": "sample",
        })
        s = report["summary"]
        self.assertEqual(s["catalogResearchCandidates"], 23)
        self.assertEqual(s["officialSourceLeads"], 14)
        self.assertEqual(s["withoutOfficialSource"], 9)
        self.assertEqual(s["companyDocumentTextsExtracted"], 14)
        self.assertEqual(s["manufacturerModelFamiliesMentioned"], 0)
        self.assertEqual(s["approvedQualityTiers"], 0)
        self.assertEqual(s["approvedPriceChanges"], 0)
        self.assertFalse(report["automaticPublicationEnabled"])
        for row in report["records"]:
            self.assertTrue(row["manualReviewRequired"])
            self.assertIsNone(row["approvedQualityTier"])
            self.assertFalse(row["exactRetailSkuIndependentlyVerified"])
            self.assertFalse(row["approvedPriceChange"])

    def test_normalization_and_model_family_does_not_approve_sku(self):
        doc = "ACRYL-PUTZ ST 10 START, 20 kg. Thickness 1-3 mm."
        evidence = stage.evaluate_document("startPutty", doc, "20kg ST10")
        self.assertTrue(evidence["modelFamilyMarkersPresent"])
        self.assertTrue(evidence["configuredPackageOrRatingMentioned"])
        self.assertTrue(evidence["technicalTopicMentions"]["thickness"])
        self.assertFalse(evidence["exactRetailSkuIndependentlyVerified"])
        self.assertFalse(evidence["manufacturerTechnicalClaimsIndependentlyTested"])

    def test_kreisel_variant_conflict_is_flagged(self):
        doc = "KREISEL M-15 441, cement groundwork 25–80 mm."
        evidence = stage.evaluate_document(
            "floorScreedMix", doc, "Sapa Kreisel 441 (10-60mm), 25kg"
        )
        self.assertTrue(evidence["modelFamilyMarkersPresent"])
        self.assertIn(
            "regional_thickness_range_disagreement_10_60_vs_25_80",
            evidence["technicalRestrictionSignals"],
        )

    def test_romanita_dry_room_limit_is_flagged(self):
        doc = "ROMANIȚA — краска для стен и потолков в сухих помещениях."
        evidence = stage.evaluate_document("interiorPaint", doc, "Romanita 7kg")
        self.assertTrue(evidence["modelFamilyMarkersPresent"])
        self.assertIn(
            "company_text_limits_product_to_dry_rooms",
            evidence["technicalRestrictionSignals"],
        )

    def test_pack_boundary_does_not_confuse_7kg_with_17kg(self):
        evidence = stage.evaluate_document(
            "interiorPaint", "ROMANIȚA in a 17 kg bucket", "Romanita 7kg"
        )
        self.assertTrue(evidence["modelFamilyMarkersPresent"])
        self.assertFalse(evidence["configuredPackageOrRatingMentioned"])

    def test_scripts_and_styles_do_not_provide_false_document_matches(self):
        raw = (
            b'<html><script>ROMANITA in dry rooms</script>'
            b'<style>.romanita{color:red}</style><p>Unrelated item</p></html>'
        )
        extracted = stage.source_text_from_html(raw)
        self.assertNotIn("ROMANITA", extracted)
        self.assertFalse(stage.evaluate_document(
            "interiorPaint", extracted, "Romanita 7kg"
        )["modelFamilyMarkersPresent"])

    def test_missing_official_model_cannot_be_approved(self):
        data42, data43 = fixtures()
        data43["records"][0]["officialSourceLeadUrl"] = "https://example.com/fake"
        with self.assertRaises(ValueError):
            stage.audit(data42, data43, fetch=lambda _: {"status": "ok", "text": "", "sha256": None})

    def test_rejects_unsafe_flags_and_coverage_drift(self):
        for flag in (
            "publishedPricesChanged", "flutterCalculationsChanged",
            "consumptionNormsChanged", "automaticPublicationEnabled",
            "automaticTierAssignmentEnabled",
        ):
            with self.subTest(flag=flag):
                data42, data43 = fixtures()
                data42[flag] = True
                with self.assertRaises(ValueError):
                    stage.audit(data42, data43, fetch=lambda _: {})
        data42, data43 = fixtures()
        data43["records"].pop()
        with self.assertRaises(ValueError):
            stage.audit(data42, data43, fetch=lambda _: {})

    def test_rejects_unknown_hosts_without_connecting(self):
        self.assertEqual(
            stage.fetch_document("https://example.com/fake")["status"],
            "untrusted_url",
        )


if __name__ == "__main__":
    unittest.main()
