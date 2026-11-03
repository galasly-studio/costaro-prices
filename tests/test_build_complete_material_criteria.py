import unittest

from scripts.build_complete_material_criteria import (
    NEW_CRITERIA,
    build_report,
)


PRIORITY_KEYS = [
    "cementPlaster",
    "electricalLightingCablePerM",
    "electricalSocketCablePerM",
    "gypsumPlaster",
    "laminatePerM2",
    "primer",
    "tileAdhesive",
    "tilePerM2",
]

PILOT_KEYS = [
    "finishPutty",
    "interiorPaint",
]


def fixture():
    keys = list(NEW_CRITERIA) + PRIORITY_KEYS + PILOT_KEYS

    families = {
        "summary": {"catalogMaterials": len(keys)},
        "families": [
            {
                "familyId": "test",
                "titleRu": "Тестовая группа",
                "catalogMaterialKeys": keys,
            }
        ],
    }

    priorities = {
        "materials": [
            {
                "catalogMaterialKey": key,
                "qualityTierApproved": False,
                "approvedForPublication": False,
                "technicalChecks": [
                    {
                        "criterionId": f"requirement{index}",
                        "criterionRu": f"Проверка {index}",
                        "requiredEvidenceRu": "Документ производителя",
                        "verifiedValue": None,
                        "evidenceProvided": False,
                        "evidenceReviewed": False,
                    }
                    for index in range(5)
                ],
            }
            for key in PRIORITY_KEYS
        ]
    }

    first_review = {
        "materials": [
            {
                "catalogMaterialKey": key,
                "detailedCriteriaStatus": (
                    "pilot_defined"
                    if key in PILOT_KEYS
                    else "material_specific_criteria_pending"
                ),
            }
            for key in keys
        ],
        "products": [
            {
                "catalogMaterialKey": key,
                "technicalFactors": [
                    f"Фактор {index}"
                    for index in range(5)
                ],
                "qualityTierApproved": False,
                "approvedForPublication": False,
            }
            for key in PILOT_KEYS
        ],
    }

    source_health = {
        "priorityMaterials": [
            {
                "catalogMaterialKey": key,
                "sourceStatus": "reachable_format_only",
            }
            for key in PRIORITY_KEYS
        ]
    }

    return families, priorities, first_review, source_health


class CompleteMaterialCriteriaTests(unittest.TestCase):

    def test_all_41_materials_have_criteria(self):
        report, queue = build_report(*fixture())

        summary = report["summary"]

        self.assertEqual(summary["catalogMaterials"], 41)
        self.assertEqual(summary["materialsWithIndividualCriteria"], 41)
        self.assertEqual(summary["existingLegacyPilots"], 2)
        self.assertEqual(summary["existingPriorityProfiles"], 8)
        self.assertEqual(summary["newIndividualProfiles"], 31)
        self.assertEqual(summary["newTechnicalRequirements"], 124)
        self.assertEqual(len(queue["tasks"]), 124)

    def test_every_new_profile_has_four_unverified_criteria(self):
        report, _ = build_report(*fixture())

        new_profiles = [
            item
            for item in report["allMaterialProfiles"]
            if item["criteriaOrigin"] == "stage40_new_specific_profile"
        ]

        self.assertEqual(len(new_profiles), 31)

        for profile in new_profiles:
            self.assertEqual(len(profile["technicalCriteria"]), 4)
            self.assertFalse(profile["qualityTierApproved"])
            self.assertFalse(profile["approvedForPublication"])

            for check in profile["technicalCriteria"]:
                self.assertIsNone(check["verifiedValue"])
                self.assertFalse(check["independentlyVerified"])

    def test_existing_pilots_and_priorities_are_preserved(self):
        report, _ = build_report(*fixture())

        origins = {
            item["catalogMaterialKey"]: item["criteriaOrigin"]
            for item in report["allMaterialProfiles"]
        }

        for key in PILOT_KEYS:
            self.assertEqual(
                origins[key],
                "existing_quality_first_pilot",
            )

        for key in PRIORITY_KEYS:
            self.assertEqual(
                origins[key],
                "existing_priority_profile",
            )

    def test_duplicate_material_family_assignment_is_rejected(self):
        data = fixture()

        data[0]["families"][0]["catalogMaterialKeys"].append(
            "decorativePlaster"
        )

        with self.assertRaises(ValueError):
            build_report(*data)

    def test_unexpected_material_is_rejected(self):
        data = fixture()

        data[0]["families"][0]["catalogMaterialKeys"][0] = (
            "unknownMaterial"
        )

        with self.assertRaises(ValueError):
            build_report(*data)

    def test_premature_verified_evidence_is_rejected(self):
        data = fixture()

        data[1]["materials"][0]["technicalChecks"][0][
            "evidenceProvided"
        ] = True

        with self.assertRaises(ValueError):
            build_report(*data)

    def test_stage39_source_mismatch_is_rejected(self):
        data = fixture()

        data[3]["priorityMaterials"][0][
            "catalogMaterialKey"
        ] = "wrongMaterial"

        with self.assertRaises(ValueError):
            build_report(*data)

    def test_no_prices_or_tiers_are_modified(self):
        report, queue = build_report(*fixture())

        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["consumptionNormsChanged"])
        self.assertFalse(report["tierMappingsChanged"])
        self.assertFalse(report["automaticPublicationEnabled"])
        self.assertFalse(report["automaticTierAssignmentEnabled"])

        self.assertEqual(
            report["summary"]["approvedForPublication"],
            0,
        )

        self.assertEqual(
            queue["summary"]["approvedForPublication"],
            0,
        )


if __name__ == "__main__":
    unittest.main()