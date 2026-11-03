import unittest

from scripts.build_bulk_sku_tier_evidence import build


def fixture():
    configured = {
        "automaticPublicationEnabled": False,
        "materials": [
            {
                "id": "testProduct",
                "name": "Тестовый товар",
                "catalogMaterialKey": "material0",
                "priceTier": None,
                "matchTerms": ["test product"],
                "sources": [
                    {
                        "store": "ShopA",
                        "url": "https://shopa.md/product",
                        "productCode": "111",
                    },
                    {
                        "store": "ShopB",
                        "url": "https://shopb.md/product",
                        "productCode": "222",
                    },
                ],
            }
        ],
    }

    observed_sources = [
        {
            "store": "ShopA",
            "url": "https://shopa.md/product",
            "productCode": "111",
            "displayedPriceMDL": 10,
            "extractionMethod": "product_structured_sku",
        },
        {
            "store": "ShopB",
            "url": "https://shopb.md/product",
            "productCode": "222",
            "displayedPriceMDL": 12,
            "extractionMethod": "product_microdata",
        },
    ]

    dashboard = {
        "summary": {
            "twoShopExactPackResearchGroups": 1,
            "materialsWithStrictResearchCandidates": 1,
        },
        "allRetailProductGroups": [
            {"observationId": "testProduct"}
        ],
        "strictRetailResearchGroups": [
            {
                "observationId": "testProduct",
                "catalogMaterialKey": "material0",
                "status": "two_shop_exact_pack_research_candidate",
                "researchMedianMDL": 11,
                "retailerPriceResearchOnly": observed_sources,
            }
        ],
    }

    criteria = {
        "allMaterialProfiles": [
            {
                "catalogMaterialKey": f"material{i}",
                "technicalFamilyId": "test_family",
                "technicalCriteria": [
                    {
                        "criterionId": "c1",
                        "criterionRu": "Назначение товара",
                    }
                ],
                "qualityTierApproved": False,
                "approvedForPublication": False,
            }
            for i in range(41)
        ]
    }

    price_audit = {
        "uncoveredMaterialKeys": [
            "material40"
        ]
    }

    return configured, dashboard, criteria, price_audit


class BulkSkuQualityGateTests(unittest.TestCase):

    def test_two_distinct_configured_sources_match(self):
        report, queue = build(*fixture())

        self.assertEqual(
            report["summary"]["strictResearchCandidates"],
            1,
        )

        self.assertEqual(
            report["summary"]["candidatesWithConsistentTwoStoreTrace"],
            1,
        )

        self.assertEqual(
            report["summary"]["materialsWithoutActualPriceMonitoring"],
            1,
        )

        self.assertEqual(len(queue["items"]), 1)

    def test_missing_retail_code_blocks_trace(self):
        data = fixture()

        data[1]["strictRetailResearchGroups"][0][
            "retailerPriceResearchOnly"
        ][1]["productCode"] = "WRONG"

        report, _ = build(*data)

        self.assertEqual(
            report["summary"]["candidatesWithConsistentTwoStoreTrace"],
            0,
        )

    def test_same_domain_does_not_count_as_independent(self):
        data = fixture()

        data[1]["strictRetailResearchGroups"][0][
            "retailerPriceResearchOnly"
        ][1]["url"] = "https://shopa.md/other-product"

        data[0]["materials"][0]["sources"][1][
            "url"
        ] = "https://shopa.md/other-product"

        report, _ = build(*data)

        self.assertEqual(
            report["summary"]["candidatesWithConsistentTwoStoreTrace"],
            0,
        )

    def test_unapproved_quality_tier_is_not_accepted(self):
        data = fixture()

        data[0]["materials"][0]["priceTier"] = "premium"

        with self.assertRaises(ValueError):
            build(*data)

    def test_catalog_prices_never_change(self):
        report, queue = build(*fixture())

        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["consumptionNormsChanged"])
        self.assertFalse(report["automaticPublicationEnabled"])
        self.assertFalse(report["automaticTierAssignmentEnabled"])

        self.assertEqual(
            report["summary"]["approvedPriceChanges"],
            0,
        )

        self.assertFalse(queue["approvedForPublication"])


if __name__ == "__main__":
    unittest.main()