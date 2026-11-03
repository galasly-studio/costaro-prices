import unittest

from scripts.audit_priority_sources_batch import (
    build_report,
    check_source_url,
)


def fixture(urls):
    keys = [f"material{i}" for i in range(len(urls))]

    family = {
        "summary": {"catalogMaterials": len(keys)},
        "families": [
            {
                "familyId": "test_family",
                "titleRu": "Тестовое семейство",
                "catalogMaterialKeys": keys,
            }
        ],
    }

    priority = {
        "materials": [
            {
                "catalogMaterialKey": key,
                "materialNameRu": key,
                "technicalFamilyId": "test_family",
                "technicalChecks": [
                    {
                        "criterionId": "technicalCriterion",
                        "verifiedValue": None,
                        "evidenceProvided": False,
                        "evidenceReviewed": False,
                    }
                ],
                "qualityTierApproved": False,
                "approvedForPublication": False,
            }
            for key in keys
        ]
    }

    leads = {
        "candidates": [
            {
                "catalogMaterialKey": key,
                "researchProductRu": key,
                "sourceUrl": url,
                "sourceSpecificity": "exact_model",
                "sourceClaims": (
                    [
                        {
                            "criterionId": "technicalCriterion",
                            "independentlyVerified": False,
                            "approvedAsQualityEvidence": False,
                        }
                    ]
                    if index % 2 == 0
                    else []
                ),
            }
            for index, (key, url) in enumerate(zip(keys, urls))
        ]
    }

    queue = {
        "tasks": [
            {"catalogMaterialKey": key}
            for key in keys
        ]
    }

    return family, priority, leads, queue


def html_success(url):
    return {
        "httpStatus": 200,
        "contentType": "text/html",
        "finalUrl": url,
        "pdfSignature": False,
        "htmlSignature": True,
        "networkError": None,
    }


def pdf_success(url):
    return {
        "httpStatus": 200,
        "contentType": "application/pdf",
        "finalUrl": url,
        "pdfSignature": True,
        "htmlSignature": False,
        "networkError": None,
    }


class BulkSourceAuditTests(unittest.TestCase):

    def test_all_eight_priority_products_in_one_pass(self):
        urls = [
            "https://supraten.md/p1",
            "https://supraten.md/p2",
            "https://latrivenetacavi.nexans.com/p1",
            "https://latrivenetacavi.nexans.com/p2",
            "https://baumit.ro/p1.pdf",
            "https://knauf.com/api/p1",
            "https://www.egger.com/p1.pdf",
            "https://storage.mtender.gov.md/get/p1",
        ]

        data = fixture(urls)

        def fetcher(url):
            if url.startswith(
                ("https://supraten.md/", "https://latrivenetacavi.nexans.com/")
            ):
                return html_success(url)
            return pdf_success(url)

        report = build_report(*data, fetcher=fetcher)
        summary = report["summary"]

        self.assertEqual(summary["priorityMaterialsAudited"], 8)
        self.assertEqual(summary["sourceRequestsAttempted"], 8)
        self.assertEqual(summary["sourcesWithReachableFormatOnly"], 8)
        self.assertEqual(summary["technicalCriteriaTotal"], 8)
        self.assertEqual(summary["manufacturerStatementsRecorded"], 4)
        self.assertEqual(summary["criteriaMissingManufacturerStatement"], 4)
        self.assertEqual(summary["approvedForPublication"], 0)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["automaticTierAssignmentEnabled"])

    def test_pdf_redirected_to_html_is_not_accepted_as_pdf(self):
        url = "https://baumit.ro/old-document.pdf"

        def changed_format(_):
            return {
                "httpStatus": 200,
                "contentType": "text/html",
                "finalUrl": "https://baumit.ro/products/product",
                "pdfSignature": False,
                "htmlSignature": True,
                "networkError": None,
            }

        report = build_report(
            *fixture([url]),
            fetcher=changed_format,
        )

        self.assertEqual(
            report["priorityMaterials"][0]["sourceStatus"],
            "document_format_mismatch",
        )

    def test_http_403_stops_remaining_requests_to_same_host(self):
        urls = [
            "https://knauf.com/api/first",
            "https://knauf.com/api/second",
        ]

        called = []

        def blocked(url):
            called.append(url)
            return {
                "httpStatus": 403,
                "contentType": None,
                "finalUrl": url,
                "pdfSignature": False,
                "htmlSignature": False,
                "networkError": None,
            }

        report = build_report(
            *fixture(urls),
            fetcher=blocked,
        )

        statuses = {
            item["sourceStatus"]
            for item in report["priorityMaterials"]
        }

        self.assertEqual(len(called), 1)
        self.assertIn("blocked_or_throttled", statuses)
        self.assertIn("skipped_after_host_block", statuses)
        self.assertEqual(
            report["summary"]["sourceRequestsAttempted"],
            1,
        )

    def test_unapproved_claims_cannot_become_quality_approval(self):
        data = fixture(["https://supraten.md/product"])

        data[2]["candidates"][0]["sourceClaims"][0][
            "approvedAsQualityEvidence"
        ] = True

        with self.assertRaises(ValueError):
            build_report(*data, fetcher=html_success)

    def test_duplicate_family_assignment_fails(self):
        data = fixture(["https://supraten.md/product"])

        data[0]["families"][0]["catalogMaterialKeys"].append(
            "material0"
        )

        with self.assertRaises(ValueError):
            build_report(*data, fetcher=html_success)

    def test_unapproved_external_host_fails(self):
        with self.assertRaises(ValueError):
            check_source_url("https://unapproved.example/product")

    def test_cross_host_response_is_not_treated_as_valid(self):
        url = "https://supraten.md/product"

        def redirected(_):
            result = html_success(url)
            result["finalUrl"] = "https://unapproved.example/product"
            return result

        report = build_report(
            *fixture([url]),
            fetcher=redirected,
        )

        self.assertEqual(
            report["priorityMaterials"][0]["sourceStatus"],
            "redirect_host_mismatch",
        )


if __name__ == "__main__":
    unittest.main()