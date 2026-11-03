import unittest

from scripts import build_official_manufacturer_batch as stage


MISSING = (
    "ceilingCdProfile",
    "ceilingDirectHangerPerPiece",
    "ceilingExtensionConnectorPerPiece",
    "ceilingUdProfile",
    "ceilingJointTape",
    "ceilingMetalScrews",
    "electricalLightingCablePerM",
    "electricalSocketCablePerM",
    "electricalSwitchPerPiece",
)


def fixture():
    keys = list(stage.OFFICIAL) + list(MISSING)

    return {
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "candidates": [
            {
                "catalogMaterialKey": key,
                "configuredProductName": key,
            }
            for key in keys
        ],
    }


class Stage43Tests(unittest.TestCase):

    def test_all_23_materials_remain_guarded(self):
        report = stage.audit(
            fixture(),
            probe=lambda _: "reachable_html_format_only",
        )

        summary = report["summary"]

        self.assertEqual(summary["researchCandidates"], 23)
        self.assertEqual(summary["officialSourceLeads"], 14)
        self.assertEqual(summary["withoutOfficialSourceLead"], 9)

        self.assertEqual(
            summary["independentlyVerifiedManufacturerModels"], 0
        )
        self.assertEqual(summary["approvedQualityTiers"], 0)
        self.assertEqual(summary["approvedPriceChanges"], 0)

        for item in report["records"]:
            self.assertFalse(item["qualityTierApproved"])
            self.assertFalse(item["priceChangeApproved"])
            self.assertTrue(item["manualReviewRequired"])

    def test_unsafe_stage42_input_is_rejected(self):
        for flag in (
            "publishedPricesChanged",
            "flutterCalculationsChanged",
            "consumptionNormsChanged",
            "automaticPublicationEnabled",
            "automaticTierAssignmentEnabled",
        ):
            with self.subTest(flag=flag):
                data = fixture()
                data[flag] = True

                with self.assertRaises(ValueError):
                    stage.audit(data, probe=lambda _: "ok")

    def test_key_conflicts_are_not_silently_accepted(self):
        data = fixture()
        data["candidates"][1]["catalogMaterialKey"] = (
            data["candidates"][0]["catalogMaterialKey"]
        )

        with self.assertRaises(ValueError):
            stage.audit(data, probe=lambda _: "ok")

    def test_unsafe_urls_are_rejected(self):
        self.assertEqual(
            stage.probe_official_source(
                "http://example.com/product"
            ),
            "rejected_untrusted_url",
        )

        self.assertEqual(
            stage.probe_official_source(
                "https://example.com/product"
            ),
            "rejected_untrusted_url",
        )

    def test_technical_conflicts_are_high_priority(self):
        report = stage.audit(
            fixture(),
            probe=lambda _: "network_unavailable",
        )

        risks = {
            row["catalogMaterialKey"]
            for row in report["records"]
            if row["highPriorityTechnicalReview"]
        }

        self.assertEqual(
            risks,
            {"floorScreedMix", "interiorPaint"},
        )


if __name__ == "__main__":
    unittest.main()