import unittest

from scripts.check_live_sku_listing import (
    MANUFACTURER_URL,
    RETAILER_URL,
    build_report,
)


def fixture():
    return {
        "status": "manual_product_provenance_review_only",
        "summary": {
            "manufacturerArticleCrossReferencesDocumented": 1,
            "unresolvedSkuTasks": 8,
        },
    }


def good_fetcher(url):
    if url == MANUFACTURER_URL:
        return (
            "<html><h1>Adeziv Nas Baund 25kg</h1>"
            "<p>Articol: 510027</p></html>"
        )

    if url == RETAILER_URL:
        return (
            "<html><h1>Class Nas BAUND 25 kg</h1>"
            "<p>12 în stoc</p>"
            "<p>Cod produs: 510027</p></html>"
        )

    raise ValueError("Unexpected URL")


class LiveSkuListingTests(unittest.TestCase):

    def test_two_matching_pages_are_research_only(self):
        report = build_report(
            fixture(),
            fetcher=good_fetcher,
        )

        summary = report["summary"]

        self.assertTrue(
            summary["sameArticleAndPackOnLivePages"]
        )
        self.assertTrue(
            summary["retailerClaimsPositiveStock"]
        )
        self.assertEqual(summary["retailerListedUnits"], 12)
        self.assertEqual(summary["fullyClosedSkuTasks"], 0)
        self.assertFalse(summary["physicalStockVerified"])
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["automaticPublicationEnabled"])

    def test_wrong_retailer_article_blocks_match(self):
        def wrong_article(url):
            if url == RETAILER_URL:
                return (
                    "<h1>Nas Baund 25 kg</h1>"
                    "<p>12 în stoc</p>"
                    "<p>Cod produs: 510028</p>"
                )

            return good_fetcher(url)

        report = build_report(
            fixture(),
            fetcher=wrong_article,
        )

        self.assertFalse(
            report["summary"]["sameArticleAndPackOnLivePages"]
        )
        self.assertFalse(
            report["summary"]["retailerClaimsPositiveStock"]
        )

    def test_blocked_site_is_not_bypassed(self):
        def blocked(url):
            if url == RETAILER_URL:
                raise OSError("HTTP 403")

            return good_fetcher(url)

        report = build_report(
            fixture(),
            fetcher=blocked,
        )

        self.assertEqual(
            report["observationState"],
            "source_access_failed_manual_review",
        )
        self.assertFalse(
            report["summary"]["sameArticleAndPackOnLivePages"]
        )

    def test_zero_stock_does_not_claim_availability(self):
        def no_stock(url):
            if url == RETAILER_URL:
                return (
                    "<h1>Nas Baund 25 kg</h1>"
                    "<p>0 în stoc</p>"
                    "<p>Cod produs: 510027</p>"
                )

            return good_fetcher(url)

        report = build_report(
            fixture(),
            fetcher=no_stock,
        )

        self.assertTrue(
            report["summary"]["sameArticleAndPackOnLivePages"]
        )
        self.assertFalse(
            report["summary"]["retailerClaimsPositiveStock"]
        )

    def test_changed_provenance_is_rejected(self):
        data = fixture()
        data["summary"]["unresolvedSkuTasks"] = 7

        with self.assertRaises(ValueError):
            build_report(data, fetcher=good_fetcher)


if __name__ == "__main__":
    unittest.main()
