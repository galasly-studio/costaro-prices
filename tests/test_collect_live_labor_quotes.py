"""Offline tests for safe, non-publishing labor quote research."""

import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_labor_prices import load
from collect_live_labor_quotes import (
    collect, download_html, html_rows, match_quote, normalize_label, normalized_unit,
    parse_value, validate_rules,
)


ROOT = Path(__file__).resolve().parents[1]
REMONT = "https://remont.md/ru/preturi/clerical/facing/"
CONSTRUCT = "https://construct.md/ru/pages/price/"
EXPERT = "https://remontexpert.md/service/tencuitor-zugrav/"
NOW = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)


def row(*cells):
    return "<tr>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>"


# Small representative table excerpts, not copies of entire websites.
REMONT_HTML = "<html><table>" + "".join([
    row("Внутренняя штукатурка стен кв.м", "65", "90", "160", "m²", "→"),
    row("Шпатлевка внутренняя кв.м", "45", "60", "90", "m²", "→"),
    row("Поклейка обоев на стены кв.м", "30", "45", "80", "m²", "→"),
    row("Покраска стен кв.м", "22", "35", "70", "m²", "→"),
    row("Монтаж гипсокартона на потолок кв.м", "80", "140", "200", "m²", "→"),
]) + "</table></html>"

CONSTRUCT_HTML = "<html><table>" + "".join([
    row("Штукатурка стен по маякам", "м2", "120"),
    row("Финишная шпаклевка стен", "м2", "50"),
    row("Поклейка обоев на стены", "м2", "45"),
    row("Покраска стен (1 слой)", "м2", "25"),
    row("Покраска стен", "м2", "45"),
    row("Монтаж гипсокартона на потолок", "м2", "170"),
]) + "</table></html>"

EXPERT_HTML = "<html><table>" + "".join([
    row("Штукатурка стен по маякам", "м²", "от 160"),
    row("Финишная шпаклевка стен", "м²", "от 75"),
    row("Покраска стен, 2 слоя", "м²", "от 80"),
    row("Стартовая шпаклевка стен", "м²", "от 65"),
]) + "</table></html>"


def fixtures():
    return (load(ROOT / "prices.json"),
            load(ROOT / "labor_market_sources.json"),
            load(ROOT / "labor_live_match_rules.json"))


def collect_fixtures(fetcher=None):
    catalog, sources, rules = fixtures()
    pages = {REMONT: REMONT_HTML, CONSTRUCT: CONSTRUCT_HTML, EXPERT: EXPERT_HTML}
    return collect(catalog, sources, rules, NOW,
                   fetcher=fetcher or (lambda url: pages[url]))


class ParsingTests(unittest.TestCase):
    def test_parser_reads_only_table_rows_not_unrelated_marketing(self):
        source = '<div>Шпаклевка стен 9999 MDL</div><script>test</script>' + row(
            "<a href='/item'>Финишная шпаклевка стен</a>", "м²", "50")
        result = html_rows(source)
        self.assertEqual(result, [["Финишная шпаклевка стен", "м²", "50"]])

    def test_m2_units_are_normalized_without_accepting_meters_or_pieces(self):
        for value in ("м2", "м²", "кв.м", "m²", "m2"):
            self.assertEqual(normalized_unit(value), "m2")
        self.assertEqual(normalized_unit("м.п."), "m")
        self.assertEqual(normalized_unit("шт"), "piece")

    def test_labels_are_exact_after_safe_typography_normalization(self):
        self.assertEqual(normalize_label("Шпатлёвка,  стен"),
                         normalize_label("Шпатлевка стен"))
        self.assertNotEqual(normalize_label("Покраска стен"),
                            normalize_label("Покраска стен (1 слой)"))

    def test_price_parser_preserves_lower_bound_semantics(self):
        self.assertEqual(parse_value("от 160"), (160.0, True))
        self.assertEqual(parse_value("45 MDL"), (45.0, False))
        self.assertEqual(parse_value("45,50"), (45.5, False))
        for value in ("бесплатно", "45–80", "45-80", "0", "99999", "Цена 40"):
            self.assertIsNone(parse_value(value))

    def test_duplicate_matching_rows_fail_closed(self):
        rule = {"label": "Поклейка обоев", "unit": "m2", "format": "single_price"}
        rows = [["Поклейка обоев", "м2", "45"], ["Поклейка обоев", "м2", "60"]]
        result = match_quote(rows, rule)
        self.assertEqual(result["status"], "rejected")
        self.assertNotIn("minimumMDL", result)

    def test_wrong_unit_does_not_create_quote(self):
        rule = {"label": "Поклейка обоев", "unit": "m2", "format": "single_price"}
        result = match_quote([["Поклейка обоев", "м.п.", "45"]], rule)
        self.assertEqual(result["reason"], "unit_mismatch")

    def test_bad_min_avg_max_order_is_rejected(self):
        rule = {"label": "Работа", "unit": "m2", "format": "min_avg_max"}
        result = match_quote([["Работа", "80", "40", "60", "m²"]], rule)
        self.assertEqual(result["reason"], "invalid_min_avg_max")

    def test_empty_or_renamed_row_is_not_a_quote(self):
        rule = {"label": "Монтаж гипсокартона на потолок", "unit": "m2",
                "format": "single_price"}
        self.assertEqual(match_quote([], rule)["status"], "not_found")
        self.assertEqual(match_quote([["Монтаж гипсокартона на стены", "м2", "170"]],
                                     rule)["status"], "not_found")

    def test_lower_bound_has_no_invented_maximum(self):
        rule = {"label": "Финишная шпаклевка стен", "unit": "m2",
                "format": "single_price"}
        result = match_quote([["Финишная шпаклевка стен", "м²", "от 75"]], rule)
        self.assertEqual(result["priceKind"], "lower_bound")
        self.assertIsNone(result["maximumMDL"])


class SafeguardTests(unittest.TestCase):
    def test_rules_cover_5_labor_keys_plus_separate_start_putty(self):
        _, sources, doc = fixtures()
        rules = validate_rules(doc, sources)
        self.assertEqual(len(rules), 14)
        self.assertEqual(len({r["workKey"] for r in rules}), 6)

    def test_unknown_site_and_key_rejected(self):
        _, sources, doc = fixtures()
        unsafe = copy.deepcopy(doc)
        unsafe["rules"][0]["url"] = "https://unknown.md/prices"
        with self.assertRaisesRegex(ValueError, "invalid_source_url"):
            validate_rules(unsafe, sources)
        unsafe = copy.deepcopy(doc)
        unsafe["rules"][0]["workKey"] = "unrelatedWork"
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            validate_rules(unsafe, sources)

    def test_publication_flag_cannot_be_enabled(self):
        _, sources, doc = fixtures()
        unsafe = copy.deepcopy(doc)
        unsafe["publicationAllowed"] = True
        with self.assertRaisesRegex(ValueError, "publication-enabled"):
            validate_rules(unsafe, sources)

    def test_cross_provider_redirect_never_counts_as_independent_source(self):
        class Response:
            headers = {"Content-Type": "text/html"}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def geturl(self):
                return "https://construct.md/ru/pages/price/"

            def read(self, size):
                return CONSTRUCT_HTML.encode("utf-8")

        class Opener:
            def open(self, request, timeout):
                return Response()

        with patch("collect_live_labor_quotes.urllib.request.build_opener",
                   return_value=Opener()):
            with self.assertRaisesRegex(ValueError, "unapproved_redirect"):
                download_html(REMONT)

    def test_duplicate_rule_rejected(self):
        _, sources, doc = fixtures()
        unsafe = copy.deepcopy(doc)
        unsafe["rules"].append(copy.deepcopy(unsafe["rules"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate_rules(unsafe, sources)

    def test_rules_are_pinned_to_documented_reference_urls(self):
        _, sources, doc = fixtures()
        unsafe = copy.deepcopy(doc)
        unsafe["rules"][0]["url"] = "https://remont.md/unrelated-page"
        with self.assertRaisesRegex(ValueError, "outside documented"):
            validate_rules(unsafe, sources)

    def test_unchanged_catalog_sources_and_rules(self):
        catalog, sources, doc = fixtures()
        before = copy.deepcopy((catalog, sources, doc))
        collect(catalog, sources, doc, NOW,
                fetcher=lambda url: {REMONT: REMONT_HTML,
                                     CONSTRUCT: CONSTRUCT_HTML,
                                     EXPERT: EXPERT_HTML}[url])
        self.assertEqual((catalog, sources, doc), before)


class CollectionTests(unittest.TestCase):
    def test_all_pilot_rows_extracted_with_three_page_fetches(self):
        calls = []
        pages = {REMONT: REMONT_HTML, CONSTRUCT: CONSTRUCT_HTML, EXPERT: EXPERT_HTML}

        def fetcher(url):
            calls.append(url)
            return pages[url]

        report = collect_fixtures(fetcher=fetcher)
        self.assertEqual(sorted(calls), sorted(pages))
        self.assertEqual(report["summary"]["mappedSourceWorkPairs"], 14)
        self.assertEqual(report["summary"]["quoteRowsExtracted"], 14)
        self.assertEqual(report["summary"]["workTypesInPilot"], 6)
        self.assertEqual(report["summary"]["publicationReadyLaborRates"], 0)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["automaticLaborPublicationEnabled"])

    def test_only_wallpaper_and_ceiling_have_two_bounded_aligned_sources(self):
        report = collect_fixtures()
        eligible = [r["workKey"] for r in report["workReview"]
                    if r["comparisonCandidateOnly"]]
        self.assertEqual(eligible, ["drywallCeilingWork", "wallpaperWork"])
        self.assertTrue(all(r["needsHumanScopeAndDateReview"] for r in report["workReview"]))

    def test_paint_coats_not_mistaken_for_generic_price(self):
        report = collect_fixtures()
        paint = [r for r in report["observations"] if r["workKey"] == "wallPaintWork"]
        self.assertEqual(len(paint), 3)
        self.assertEqual(sum(r["scopeStatus"] == "review_required" for r in paint), 2)
        exact = next(r for r in paint if r["source"] == "remontexpert.md")
        self.assertEqual(exact["priceKind"], "lower_bound")
        self.assertEqual(exact["minimumMDL"], 80)
        self.assertFalse(exact["priceDateVerified"])

    def test_blocked_host_not_substituted_with_old_price(self):
        pages = {REMONT: REMONT_HTML, CONSTRUCT: CONSTRUCT_HTML, EXPERT: EXPERT_HTML}

        def fetcher(url):
            if url == REMONT:
                raise urllib.error.HTTPError(url, 403, "Forbidden", None, None)
            return pages[url]

        report = collect_fixtures(fetcher=fetcher)
        self.assertEqual(report["summary"]["quoteRowsExtracted"], 9)
        self.assertTrue(all(r["status"] != "research_quote" for r in
                            report["observations"] if r["url"] == REMONT))
        self.assertEqual(report["summary"]["publicationReadyLaborRates"], 0)

    def test_missing_html_table_reports_not_found_not_unverified_price(self):
        report = collect_fixtures(fetcher=lambda _: "<html>100 MDL generic ad</html>")
        self.assertEqual(report["summary"]["quoteRowsExtracted"], 0)
        self.assertEqual(report["summary"]["workTypesWithTwoBoundedAlignedSourcesForComparison"], 0)

    def test_page_challenge_rejected_even_with_marketing_price(self):
        report = collect_fixtures(fetcher=lambda _: "<title>Just a moment...</title>" +
                                  CONSTRUCT_HTML)
        self.assertEqual(report["summary"]["pagesParsed"], 0)
        self.assertEqual(report["summary"]["quoteRowsExtracted"], 0)


if __name__ == "__main__":
    unittest.main()
