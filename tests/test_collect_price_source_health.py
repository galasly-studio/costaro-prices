"""Network-free regression tests for transparent, rate-limit-safe collection."""

from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import socket
import sys
import tempfile
import unittest
from unittest.mock import patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import collect_prices as collector  # noqa: E402


class SourceFailureClassificationTests(unittest.TestCase):
    def test_http_status_is_recorded_without_raw_server_response(self):
        error = urllib.error.HTTPError("https://macons.md/a", 403,
                                       "Forbidden", None, None)
        self.assertEqual(collector.error_category(error), "http_403")
        error = urllib.error.HTTPError("https://domic.md/a", 429,
                                       "Too Many Requests", None, None)
        self.assertEqual(collector.error_category(error), "http_429")

    def test_network_failure_classes(self):
        self.assertEqual(collector.error_category(TimeoutError()), "timeout")
        self.assertEqual(collector.error_category(
            urllib.error.URLError(socket.gaierror("not resolved"))), "dns_error")
        self.assertEqual(collector.error_category(
            urllib.error.URLError("server unavailable")), "network_error")
        self.assertEqual(collector.error_category(
            ValueError("Unexpected content type")), "unexpected_content_type")
        self.assertEqual(collector.error_category(
            ValueError("Unexpected redirect")), "unexpected_redirect")

    def test_store_summary_counts_only_real_price_candidates(self):
        materials = [{"observations": [
            {"store": "Macons", "status": "unavailable", "error": "http_403"},
            {"store": "Macons", "status": "unavailable", "error": "skipped_after_http_403"},
            {"store": "Domic", "status": "candidate", "extractionMethod": "structured_data"},
            {"store": "Domic", "status": "ambiguous", "error": "multiple_possible_prices"},
        ]}]
        result = {entry["store"]: entry for entry in collector.source_health(materials)}
        self.assertEqual(result["Macons"]["total"], 2)
        self.assertEqual(result["Macons"]["candidate"], 0)
        self.assertEqual(result["Macons"]["errors"],
                         {"http_403": 1, "skipped_after_http_403": 1})
        self.assertEqual(result["Domic"]["candidate"], 1)
        self.assertEqual(result["Domic"]["ambiguous"], 1)
        self.assertEqual(result["Domic"]["methods"], {"structured_data": 1})


class SafeCollectionFlowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.source_file = root / "sources.json"
        self.output_file = root / "observations.json"
        self.source_file.write_text(json.dumps({
            "schemaVersion": 1, "country": "MD", "currency": "MDL",
            "automaticPublicationEnabled": False,
            "materials": [{
                "id": "example", "name": "example", "matchTerms": ["example"],
                "sources": [
                    {"store": "Macons", "url": "https://macons.md/one", "productCode": "1"},
                    {"store": "Macons", "url": "https://macons.md/two", "productCode": "2"},
                    {"store": "Domic", "url": "https://domic.md/one", "productCode": "3"},
                ],
            }],
        }), encoding="utf-8")

    def run_collector(self, refusal):
        urls = []

        def download(url):
            urls.append(url)
            if "macons.md" in url:
                raise urllib.error.HTTPError(url, refusal, "Blocked", None, None)
            return "<html>trusted</html>"

        with patch.object(collector, "SOURCES", self.source_file), \
                patch.object(collector, "OUTPUT", self.output_file), \
                patch.object(collector, "download_page", side_effect=download), \
                patch.object(collector, "extract_price", return_value=(100, "candidate", "product_microdata")), \
                redirect_stdout(StringIO()):
            collector.main()
        return json.loads(self.output_file.read_text(encoding="utf-8")), urls

    def test_http_403_stops_same_host_but_keeps_other_shops(self):
        result, urls = self.run_collector(403)
        self.assertEqual(len(urls), 2)
        self.assertEqual(result["materials"][0]["observations"][0]["error"], "http_403")
        self.assertEqual(result["materials"][0]["observations"][1]["error"],
                         "skipped_after_http_403")
        self.assertEqual(result["materials"][0]["observations"][2]["price"], 100)
        self.assertEqual(result["sourceHealth"][0]["candidate"], 1)
        self.assertTrue(all(item["readyForPublication"] is False
                            for item in result["materials"]))

    def test_http_429_stops_repeat_requests(self):
        result, urls = self.run_collector(429)
        self.assertEqual(len(urls), 2)
        self.assertEqual(result["materials"][0]["observations"][1]["error"],
                         "skipped_after_http_429")


if __name__ == "__main__":
    unittest.main()
