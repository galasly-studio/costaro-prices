import copy
import unittest

from scripts.build_market_decision_dashboard import evaluate


def fixture():
    materials = {
        f"material{i}": {
            "budget": 1,
            "standard": 2,
            "premium": 3,
        }
        for i in range(41)
    }

    labor = {
        f"work{i}": {
            "budget": 10,
            "standard": 20,
            "premium": 30,
        }
        for i in range(37)
    }

    catalog = {
        "country": "MD",
        "currency": "MDL",
        "materialPrices": materials,
        "laborPrices": labor,
    }

    observations = {
        "currency": "MDL",
        "materials": [
            {
                "id": "productA",
                "observations": [
                    {
                        "store": "Store A",
                        "url": "https://example.test/a",
                        "productCode": "A1",
                        "price": 12.0,
                        "status": "candidate",
                        "extractionMethod": "product_structured_sku",
                    },
                    {
                        "store": "Store B",
                        "url": "https://example.test/b",
                        "productCode": "B1",
                        "price": 14.0,
                        "status": "candidate",
                        "extractionMethod": "product_microdata",
                    },
                ],
            },
            {
                "id": "productB",
                "observations": [
                    {
                        "store": "Store A",
                        "url": "https://example.test/c",
                        "productCode": "C1",
                        "price": 11.0,
                        "status": "candidate",
                        "extractionMethod": "visible_text",
                    },
                    {
                        "store": "Store B",
                        "url": "https://example.test/d",
                        "productCode": "D1",
                        "price": 13.0,
                        "status": "candidate",
                        "extractionMethod": "visible_text",
                    },
                ],
            },
        ],
    }

    audited = {
        "materials": [
            {
                "id": product_id,
                "catalogMaterialKey": material,
                "comparisonReady": True,
                "verifiedForPublication": False,
            }
            for product_id, material in [
                ("productA", "material0"),
                ("productB", "material1"),
            ]
        ],
    }

    pack = {
        "summary": {
            "catalogTierSlotsWithLiveComparableExactPacks": 3,
        },
        "products": [
            {
                "id": product_id,
                "catalogMaterialKey": material,
                "retailSkuMissing": False,
                "twoShopMetadataPresent": True,
                "marketComparisonReady": True,
                "reviewedTier": False,
                "approvedForPublication": False,
                "tierChecks": {
                    tier: {"status": "exact"}
                    for tier in ("budget", "standard", "premium")
                },
            }
            for product_id, material in [
                ("productA", "material0"),
                ("productB", "material1"),
            ]
        ],
    }

    labor_audit = {
        "rows": [
            {
                "key": key,
                "status": (
                    "COMPARISON READY"
                    if index < 5
                    else "NEEDS REVIEW"
                ),
                "independentSources": 2 if index < 5 else 0,
            }
            for index, key in enumerate(labor)
        ],
    }

    quotes = {"observations": []}

    criteria = {
        "allMaterialProfiles": [
            {
                "catalogMaterialKey": key,
                "qualityTierApproved": False,
                "approvedForPublication": False,
            }
            for key in materials
        ]
    }

    readiness = {
        "status": "held",
        "explicitPublicationApproved": False,
    }

    return (
        catalog,
        observations,
        audited,
        pack,
        labor_audit,
        quotes,
        criteria,
        readiness,
    )


class MarketDecisionDashboardTests(unittest.TestCase):

    def test_all_materials_and_labor_are_covered(self):
        report, queue = evaluate(*fixture())

        summary = report["summary"]

        self.assertEqual(summary["catalogMaterials"], 41)
        self.assertEqual(summary["catalogLaborRates"], 37)
        self.assertEqual(summary["individualResearchDecisions"], 78)
        self.assertEqual(len(queue["items"]), 78)

    def test_two_product_scoped_stores_form_research_candidate(self):
        report, _ = evaluate(*fixture())

        self.assertEqual(
            report["summary"]["twoShopExactPackResearchGroups"],
            1,
        )

        candidate = report["strictRetailResearchGroups"][0]

        self.assertEqual(candidate["observationId"], "productA")
        self.assertEqual(candidate["researchMedianMDL"], 13.0)
        self.assertFalse(candidate["qualityTierApproved"])
        self.assertFalse(candidate["approvedForPublication"])

    def test_visible_text_is_not_treated_as_strict_sku_price(self):
        report, _ = evaluate(*fixture())

        rows = {
            row["observationId"]: row
            for row in report["allRetailProductGroups"]
        }

        self.assertEqual(
            rows["productB"]["status"],
            "requires_more_research",
        )

    def test_wrong_package_blocks_candidate(self):
        data = fixture()

        data[3]["products"][0]["tierChecks"] = {
            tier: {"status": "different_pack"}
            for tier in ("budget", "standard", "premium")
        }

        report, _ = evaluate(*data)

        self.assertEqual(
            report["summary"]["twoShopExactPackResearchGroups"],
            0,
        )

    def test_publication_state_change_is_not_ignored(self):
        data = fixture()
        data[7]["explicitPublicationApproved"] = True

        with self.assertRaises(ValueError):
            evaluate(*data)

    def test_duplicate_observation_id_is_rejected(self):
        data = fixture()
        data[1]["materials"].append(
            copy.deepcopy(data[1]["materials"][0])
        )

        with self.assertRaises(ValueError):
            evaluate(*data)

    def test_no_published_price_or_tier_change(self):
        report, decisions = evaluate(*fixture())

        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["consumptionNormsChanged"])
        self.assertFalse(report["automaticPublicationEnabled"])
        self.assertFalse(report["automaticTierAssignmentEnabled"])

        self.assertEqual(
            report["summary"]["materialPricesApprovedForPublication"],
            0,
        )

        self.assertEqual(
            report["summary"]["laborRatesApprovedForPublication"],
            0,
        )

        self.assertFalse(decisions["approvedForPublication"])


if __name__ == "__main__":
    unittest.main()