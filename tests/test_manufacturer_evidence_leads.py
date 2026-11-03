import copy
from datetime import date
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_manufacturer_evidence_leads import (
    LEADS,
    build,
    render_markdown,
)
from build_priority_material_criteria import (
    build as build_priority,
)
from test_priority_material_criteria import inputs


def fixture():
    catalog, family_report = inputs()
    return build_priority(catalog, family_report)


class ManufacturerEvidenceLeadTests(unittest.TestCase):

    def test_all_eight_materials_have_research_sources(self):
        report = build(fixture(), today=date(2026, 11, 3))

        self.assertEqual(report["summary"]["priorityMaterials"], 8)
        self.assertEqual(
            report["summary"]["candidateTechnicalSources"], 8
        )
        self.assertEqual(len(report["candidates"]), 8)

    def test_no_claim_is_independently_verified(self):
        report = build(fixture(), today=date(2026, 11, 3))

        self.assertEqual(
            report["summary"]["independentlyVerifiedClaims"], 0
        )
        self.assertEqual(report["summary"]["qualityTiersApproved"], 0)
        self.assertEqual(report["summary"]["approvedForPublication"], 0)

        for item in report["candidates"]:
            self.assertFalse(item["qualityTierApproved"])
            self.assertFalse(item["approvedForPublication"])
            self.assertFalse(
                item["exactRetailSkuInMoldovaVerified"]
            )
            for claim in item["sourceClaims"]:
                self.assertFalse(claim["independentlyVerified"])

    def test_source_is_never_a_price_update(self):
        report = build(fixture(), today=date(2026, 11, 3))

        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["tierMappingsChanged"])
        self.assertFalse(report["automaticTierAssignmentEnabled"])
        self.assertFalse(report["automaticPublicationEnabled"])

    def test_missing_source_is_rejected(self):
        altered = copy.deepcopy(LEADS)
        altered.pop("primer")

        with self.assertRaises(ValueError):
            build(fixture(), altered, today=date(2026, 11, 3))

    def test_unknown_criterion_is_rejected(self):
        altered = copy.deepcopy(LEADS)
        altered["tileAdhesive"]["claims"] = [
            ("inventedQualityTier", "Недопустимое утверждение")
        ]

        with self.assertRaises(ValueError):
            build(fixture(), altered, today=date(2026, 11, 3))

    def test_duplicate_criterion_is_rejected(self):
        altered = copy.deepcopy(LEADS)
        claims = list(altered["primer"]["claims"])
        claims.append(claims[0])
        altered["primer"]["claims"] = claims

        with self.assertRaises(ValueError):
            build(fixture(), altered, today=date(2026, 11, 3))

    def test_unapproved_source_domain_is_rejected(self):
        altered = copy.deepcopy(LEADS)
        altered["primer"]["url"] = "https://unknown.example/primer.pdf"

        with self.assertRaises(ValueError):
            build(fixture(), altered, today=date(2026, 11, 3))

    def test_old_research_is_marked_for_refresh(self):
        report = build(fixture(), today=date(2027, 3, 1))

        self.assertEqual(
            report["summary"]["sourcesNeedingManualRefresh"], 8
        )
        self.assertTrue(
            all(
                item["sourceNeedsManualRefresh"]
                for item in report["candidates"]
            )
        )

    def test_unsafe_priority_report_is_rejected(self):
        source = fixture()
        source["automaticPublicationEnabled"] = True

        with self.assertRaises(ValueError):
            build(source, today=date(2026, 11, 3))

    def test_input_is_unchanged(self):
        source = fixture()
        before = copy.deepcopy(source)

        build(source, today=date(2026, 11, 3))

        self.assertEqual(source, before)

    def test_russian_report_lists_all_eight_sources(self):
        report = build(fixture(), today=date(2026, 11, 3))
        markdown = render_markdown(report)

        for lead in LEADS.values():
            self.assertIn(lead["nameRu"], markdown)

        self.assertIn("Утверждённых категорий качества: **0**", markdown)


if __name__ == "__main__":
    unittest.main()