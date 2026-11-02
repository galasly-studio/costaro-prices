"""Offline guardrails for manufacturer-consumption research (not price approval)."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_consumption_alignment import audit, main, markdown  # noqa: E402
from validate_app_catalog import load  # noqa: E402


def fixture():
    return [load(ROOT / name) for name in (
        "prices.json", "app_embedded_baseline.json", "price_sources.json",
        "material_consumption_evidence.json")]


def product(evidence, item_id):
    return next(row for row in evidence["products"] if row["id"] == item_id)


class ManufacturerConsumptionAuditTests(unittest.TestCase):
    def test_six_individually_reviewed_products_and_no_approvals(self):
        f = fixture()
        frozen = json.dumps(f, ensure_ascii=False, sort_keys=True)
        result = audit(*f)
        self.assertEqual(result["summary"], {
            "reviewedProducts": 6,
            "preliminaryConsumptionCompatible": 4,
            "consumptionReviewRequired": 2,
            "unapprovedAlternatives": 1,
        })
        self.assertEqual(json.dumps(f, ensure_ascii=False, sort_keys=True), frozen)
        self.assertFalse(result["publishedPricesChanged"])
        self.assertFalse(result["flutterCalculationsChanged"])
        self.assertFalse(result["automaticTierApprovalEnabled"])
        self.assertTrue(result["appNormSourceNeedsReleaseRecheck"])
        self.assertTrue(all(not item["approvedForPublication"] and
                            not item["tierQualityApproved"] for item in result["products"]))

    def test_sansiro_never_passes_generic_two_coat_norm(self):
        rows = {row["id"]: row for row in audit(*fixture())["products"]}
        sansiro = rows["sansiro_7kg"]
        self.assertEqual(sansiro["status"], "app_norm_below_manufacturer_minimum")
        self.assertTrue(sansiro["requiresConsumptionReview"])
        self.assertEqual(sansiro["manufacturerKgPerM2ForConfiguredCoats"],
                         {"minimum": 0.4, "maximum": 0.44})
        self.assertEqual(sansiro["examplePackages"], {
            "appPreliminary": 3, "manufacturerMinimum": 3, "manufacturerMaximum": 4})

    def test_mesterul_manole_upper_range_can_need_eleven_buckets(self):
        rows = {row["id"]: row for row in audit(*fixture())["products"]}
        mester = rows["glet_mesterul_manole_8kg"]
        self.assertEqual(mester["status"], "wide_consumption_range_requires_review")
        self.assertEqual(mester["examplePackages"], {
            "appPreliminary": 4, "manufacturerMinimum": 3, "manufacturerMaximum": 11})

    def test_other_four_preliminary_compatible_but_not_approved(self):
        output = audit(*fixture())
        good = {row["id"] for row in output["products"]
                if not row["requiresConsumptionReview"]}
        self.assertEqual(good, {"glet_b62_satroc_8kg", "glet_satroc_8kg",
                                "romanita_7kg", "euroton_lav_7kg"})
        self.assertTrue(all(not row["approvedForPublication"] for row in output["products"]))

    def test_alternative_is_not_configured_or_approved(self):
        alt = audit(*fixture())["alternativeForHumanResearch"]
        self.assertEqual(alt["manufacturerProductCode"], "6000378")
        self.assertTrue(alt["compatibleConsumptionCandidate"])
        self.assertFalse(alt["configuredForCollection"])
        self.assertFalse(alt["approvedForPublication"])

    def test_workflow_report_is_honest_and_explains_ceiling_exclusion(self):
        report = markdown(audit(*fixture()))
        self.assertIn("Только исследование", report)
        self.assertIn("Sansiro", report)
        self.assertIn("подготовка потолка", report)
        self.assertIn("не утверждены", report)

    def test_unexpected_or_duplicate_manufacturer_product_id_is_rejected(self):
        for bad_id in ("not_six_products", "glet_b62_satroc_8kg"):
            f = fixture()
            f[3]["products"][0]["id"] = bad_id
            with self.assertRaisesRegex(ValueError, "product IDs|product IDs differ|review set"):
                audit(*f)

    def test_missing_evidence_or_wrong_market_is_rejected(self):
        for field in ("products", "appNormSnapshot", "alternativesForHumanResearch"):
            f = fixture()
            f[3].pop(field)
            with self.assertRaises(ValueError):
                audit(*f)
        f = fixture()
        f[3]["currency"] = "EUR"
        with self.assertRaisesRegex(ValueError, "technical evidence"):
            audit(*f)

    def test_flutter_norm_snapshot_fails_closed_when_edited(self):
        for attribute, wrong_value in (
            ("kgPerM2ForConfiguredCoats", 0.35),
            ("coats", 1), ("codeConstant", "MaterialNorms.wrong"),
            ("scope", "ceiling_preparation"),
        ):
            f = fixture()
            f[3]["appNormSnapshot"][1][attribute] = wrong_value
            with self.assertRaisesRegex(ValueError, "Flutter norm snapshot"):
                audit(*f)

    def test_changed_pack_or_tier_or_material_must_be_reviewed(self):
        for mode in ("source_pack", "evidence_pack", "source_tier", "material", "already_tiered"):
            f = fixture()
            source = next(x for x in f[2]["materials"] if x["id"] == "sansiro_7kg")
            evidence = product(f[3], "sansiro_7kg")
            if mode == "source_pack":
                source["packageWeightKg"] = 10
            elif mode == "evidence_pack":
                evidence["packageWeightKg"] = 10
            elif mode == "source_tier":
                source["tierCandidateForReview"] = "budget"
            elif mode == "material":
                evidence["catalogMaterialKey"] = "finishPutty"
            else:
                source["priceTier"] = "premium"
            with self.subTest(mode=mode), self.assertRaises(ValueError):
                audit(*f)

    def test_untrusted_or_invalid_manufacturer_url_is_rejected(self):
        for value in ("http://supraten.md/item", "https://evil.example/item",
                      "https://supraten.md@evil.example/item",
                      "https://supraten.md:123/item", None):
            f = fixture()
            product(f[3], "sansiro_7kg")["manufacturerUrl"] = value
            with self.subTest(url=value), self.assertRaisesRegex(ValueError, "identity"):
                audit(*f)

    def test_malformed_ranges_never_produce_a_price_recommendation(self):
        for minimum, maximum in ((0, 0.5), (0.4, -1), (0.5, 0.1),
                                 (True, 0.7), (float("nan"), 0.7),
                                 (float("inf"), 0.7)):
            f = fixture()
            product(f[3], "glet_satroc_8kg")["manufacturerConsumptionKgPerM2PerCoat"] = {
                "minimum": minimum, "maximum": maximum}
            with self.subTest(bounds=(minimum, maximum)), self.assertRaisesRegex(
                    ValueError, "consumption range"):
                audit(*f)

    def test_automatic_publication_setting_must_remain_disabled(self):
        f = fixture()
        f[2]["automaticPublicationEnabled"] = True
        with self.assertRaisesRegex(ValueError, "policy mismatch"):
            audit(*f)

    def test_flipped_catalog_is_not_treated_as_approved(self):
        f = fixture()
        f[0]["materialPrices"]["finishPutty"]["budget"]["amount"] = 20
        with self.assertRaises(ValueError):
            audit(*f)

    def test_research_alternative_cannot_sneak_into_live_sources(self):
        f = fixture()
        f[2]["materials"].append({
            "id": "euroton_eco_7kg", "name": "Vopsea Euroton Eco 7kg"})
        with self.assertRaisesRegex(ValueError, "must not be configured"):
            audit(*f)

    def test_invalid_alternative_is_rejected(self):
        for field, value in (("manufacturerProductCode", "wrong"),
                             ("status", "approved"),
                             ("secondShopUrl", "http://gebhardt.md/p"),
                             ("name", "Other Paint")):
            f = fixture()
            f[3]["alternativesForHumanResearch"][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError,
                                                                      "alternative product"):
                audit(*f)

    def test_example_area_must_be_positive_and_finite(self):
        for area in (0, -1, True, float("nan"), float("inf")):
            with self.subTest(area=area), self.assertRaisesRegex(ValueError, "area"):
                audit(*fixture(), area_m2=area)

    def test_cli_protects_sources_and_refuses_existing_report(self):
        with tempfile.TemporaryDirectory() as dirname:
            directory = Path(dirname)
            inputs = [ROOT / name for name in (
                "prices.json", "app_embedded_baseline.json", "price_sources.json",
                "material_consumption_evidence.json")]
            args = [flag for path, key in zip(inputs, (
                "--catalog", "--baseline", "--sources", "--evidence"))
                for flag in (key, str(path))]
            self.assertRaisesRegex(ValueError, "overwrite any source", main,
                                   args + ["--report", str(inputs[0])])
            report = directory / "report.json"
            text = directory / "report.md"
            main(args + ["--report", str(report), "--markdown", str(text)])
            produced = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(produced["summary"]["reviewedProducts"], 6)
            self.assertIn("Только исследование", text.read_text(encoding="utf-8"))
            with self.assertRaisesRegex(FileExistsError, "already exists"):
                main(args + ["--report", str(report), "--markdown", str(text)])


if __name__ == "__main__":
    unittest.main()
