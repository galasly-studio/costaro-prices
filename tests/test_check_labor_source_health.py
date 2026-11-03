"""Offline safety tests: page reachability is never price verification."""

import copy
from datetime import date
from pathlib import Path
import sys
import unittest
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_labor_prices import LABOR_KEYS
from check_labor_source_health import (
    check_sources, error_category, looks_like_block_page, validate_url,
)


TODAY = date(2026, 11, 2)


def catalog():
    return {
        "schemaVersion": 1, "catalogVersion": "0.1.0", "country": "MD",
        "currency": "MDL", "status": "draft", "automaticUpdatesEnabled": False,
        "laborPrices": {k: {"budget": 30, "standard": 45, "premium": 60}
                        for k in LABOR_KEYS},
        "materialPrices": {f"material_{n}": {} for n in range(41)},
    }


def ref(url, key="puttyWork", checked="2026-10-31", unit="m2"):
    return {"url": url, "checkedOn": checked, "scope": key,
            "unit": unit, "min": 35, "max": 85}


class UrlSafetyTests(unittest.TestCase):
    def test_explicit_configured_provider_is_accepted(self):
        self.assertEqual(validate_url("https://www.remont.md/ru/prices"), "remont.md")

    def test_topmaster_only_exact_https_host_is_accepted(self):
        self.assertEqual(
            validate_url("https://topmaster.md/price/montazhnyje-raboty-po-santehnike/"),
            "topmaster.md")
        for url in ("http://topmaster.md/price/", "https://topmaster.md.evil.md/a",
                    "https://user:password@topmaster.md/a", "https://topmaster.md:1234/a"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_euroremont_research_host_is_exact(self):
        url = "https://euroremontstyle.md/remont-kvartir-ceny"
        self.assertEqual(validate_url(url), "euroremontstyle.md")
        for invalid in (
            "http://euroremontstyle.md/remont-kvartir-ceny",
            "https://euroremontstyle.md.evil.com/prices",
            "https://user:pass@euroremontstyle.md/prices",
            "https://euroremontstyle.md:8080/prices",
        ):
            with self.subTest(url=invalid):
                with self.assertRaises(ValueError):
                    validate_url(invalid)

    def test_url_unsafe_hosts_rejected(self):
        for url in (
            "http://remont.md/prices", "https://evil.md/prices",
            "https://remont.md.evil.md/prices", "https://127.0.0.1/private",
            "https://remont.md:8443/prices", "https://user:pass@remont.md/prices",
            "https://remont.md/\r\nInjected: value", "file:///etc/passwd",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_url(url)

    def test_block_page_is_not_reachable_content(self):
        self.assertTrue(looks_like_block_page("<title>Just a moment...</title>"))
        self.assertFalse(looks_like_block_page("<title>Prices</title>"))

    def test_http_rate_limit_classification(self):
        error = urllib.error.HTTPError("https://remont.md/x", 429, "", None, None)
        self.assertEqual(error_category(error), "http_429")


class ReadOnlyChecks(unittest.TestCase):
    def test_zero_sources_creates_only_research_results(self):
        result = check_sources(catalog(), {"sources": {}}, TODAY,
                               fetcher=lambda _: self.fail("unexpected network"),
                               pause=lambda _: None)
        s = result["summary"]
        self.assertEqual(s["catalogLaborRates"], 37)
        self.assertEqual(s["laborRatesWithNoCurrentReferences"], 37)
        self.assertEqual(s["laborRatesLivePriceVerified"], 0)
        self.assertFalse(result["publishedPricesChanged"])
        self.assertFalse(result["automaticLaborPublicationEnabled"])

    def test_two_hosts_dont_verify_prices(self):
        refs = {"sources": {"puttyWork": [
            ref("https://remont.md/one"), ref("https://construct.md/two"),
        ]}}
        result = check_sources(catalog(), refs, TODAY,
                               fetcher=lambda _: "<html>Example price list</html>",
                               pause=lambda _: None)
        row = next(r for r in result["workRates"] if r["key"] == "puttyWork")
        self.assertEqual(row["currentIndependentDomains"], 2)
        self.assertEqual(row["reachableIndependentDomains"], 2)
        self.assertFalse(row["livePriceVerified"])
        self.assertEqual(row["nextAction"], "verify_exact_live_work_rate_and_scope")
        self.assertEqual(result["summary"]["laborRatesLivePriceVerified"], 0)

    def test_same_page_for_multiple_types_fetched_only_once(self):
        url = "https://construct.md/ru/pages/price/"
        requested = []

        def fetcher(value):
            requested.append(value)
            return "<html>hello</html>"

        refs = {"sources": {
            "puttyWork": [ref(url)],
            "plasterWork": [ref(url, key="plasterWork")],
        }}
        result = check_sources(catalog(), refs, TODAY, fetcher=fetcher,
                               pause=lambda _: None)
        self.assertEqual(requested, [url])
        self.assertEqual(result["summary"]["uniqueUrlsConfiguredAndCurrent"], 1)

    def test_403_blocks_remaining_urls_at_same_host_only(self):
        calls = []

        def fetcher(url):
            calls.append(url)
            if "remont.md" in url:
                raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
            return "<html>public</html>"

        refs = {"sources": {"puttyWork": [
            ref("https://remont.md/a"), ref("https://remont.md/b"),
            ref("https://construct.md/c"),
        ]}}
        result = check_sources(catalog(), refs, TODAY, fetcher=fetcher,
                               pause=lambda _: None)
        self.assertEqual(len(calls), 2)
        self.assertEqual(result["summary"]["uniqueUrlsSkipped"], 1)
        self.assertEqual(result["summary"]["uniqueUrlsReachable"], 1)
        self.assertEqual(result["errorCategories"]["http_403"], 1)

    def test_stale_reference_does_not_become_current_on_http_200(self):
        result = check_sources(catalog(), {"sources": {"puttyWork": [
            ref("https://construct.md/a", checked="2025-01-01"),
        ]}}, TODAY, fetcher=lambda _: self.fail("stale fetch"),
            pause=lambda _: None)
        row = next(r for r in result["workRates"] if r["key"] == "puttyWork")
        self.assertEqual(row["staleReferences"], 1)
        self.assertEqual(row["currentReferences"], 0)
        self.assertEqual(row["nextAction"], "find_first_source")

    def test_bad_unit_and_unsupported_host_are_not_fetched(self):
        result = check_sources(catalog(), {"sources": {"puttyWork": [
            ref("https://construct.md/a", unit="piece"),
            ref("https://evil.md/a"),
        ]}}, TODAY, fetcher=lambda _: self.fail("invalid fetch"),
            pause=lambda _: None)
        row = next(r for r in result["workRates"] if r["key"] == "puttyWork")
        self.assertEqual(row["invalidReferences"], 2)

    def test_http_200_challenge_does_not_count_as_reachable(self):
        result = check_sources(catalog(), {"sources": {"puttyWork": [
            ref("https://construct.md/a"),
        ]}}, TODAY, fetcher=lambda _: "<title>Verify you are human</title>",
            pause=lambda _: None)
        self.assertEqual(result["summary"]["uniqueUrlsReachable"], 0)
        self.assertEqual(result["errorCategories"]["challenge_page"], 1)

    def test_unchanged_input_objects(self):
        data = catalog()
        refs = {"sources": {"puttyWork": [ref("https://remont.md/a")]}}
        previous = (copy.deepcopy(data), copy.deepcopy(refs))
        check_sources(data, refs, TODAY, fetcher=lambda _: "<html>ok</html>",
                      pause=lambda _: None)
        self.assertEqual((data, refs), previous)

    def test_reject_unsafe_catalog_even_if_site_works(self):
        data = catalog()
        data["laborPrices"]["puttyWork"]["budget"] = 100000
        with self.assertRaisesRegex(ValueError, "Invalid catalog"):
            check_sources(data, {"sources": {}}, TODAY,
                          fetcher=lambda _: self.fail("network"))

    def test_reject_unknown_work_key(self):
        with self.assertRaisesRegex(ValueError, "Unexpected source keys"):
            check_sources(catalog(), {"sources": {"notOurKey": []}}, TODAY,
                          fetcher=lambda _: self.fail("network"))


if __name__ == "__main__":
    unittest.main()
