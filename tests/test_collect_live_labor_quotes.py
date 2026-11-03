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
    parse_value, parse_topmaster_amount, validate_rules,
)


ROOT = Path(__file__).resolve().parents[1]
REMONT = "https://remont.md/ru/preturi/clerical/facing/"
CONSTRUCT = "https://construct.md/ru/pages/price/"
EXPERT = "https://remontexpert.md/service/tencuitor-zugrav/"
BUILDING = "https://remont.md/ru/preturi/clerical/building_installation_work/"
ELECTRIC = "https://remont.md/ru/preturi/clerical/repair_electric/"
TILING = "https://remont.md/ru/preturi/clerical/tiling/"
TOPMASTER = "https://topmaster.md/price/montazhnyje-raboty-po-santehnike/"
EURO = "https://euroremontstyle.md/remont-kvartir-ceny"
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
    # Stage 19 pilot must remain covered independently of the new, wider stage.
    rules = {**rules, "rules": rules["rules"][:14]}
    pages = {REMONT: REMONT_HTML, CONSTRUCT: CONSTRUCT_HTML, EXPERT: EXPERT_HTML}
    return collect(catalog, sources, rules, NOW,
                   fetcher=fetcher or (lambda url: pages[url]))


class ParsingTests(unittest.TestCase):
    def test_topmaster_explicit_currency_and_price_label_parser(self):
        self.assertEqual(parse_topmaster_amount("мин 30 MDL", "мин"), 30)
        self.assertEqual(parse_topmaster_amount("макс 100 MDL", "макс"), 100)
        self.assertEqual(parse_topmaster_amount("в среднем 90 MDL", "в среднем"), 90)
        for invalid in ("мин 30 RUB", "30 MDL", "мин от 30 MDL", "мин 0 MDL"):
            self.assertIsNone(parse_topmaster_amount(invalid, "мин"))

    def test_topmaster_exact_per_meter_table_can_only_create_research_quote(self):
        rule = {"format": "topmaster_min_max_avg", "unit": "m",
                "label": "Установка труб канализации м/п"}
        result = match_quote([["Установка труб канализации м/п", "мин 100 MDL",
                               "макс 200 MDL", "в среднем 114 MDL", "Все цены"]], rule)
        self.assertEqual(result["status"], "research_quote")
        self.assertEqual(result["unit"], "m")
        self.assertEqual([result[k] for k in ("minimumMDL", "averageMDL", "maximumMDL")],
                         [100, 114, 200])

    def test_topmaster_point_or_wrong_unit_does_not_become_meter(self):
        rule = {"format": "topmaster_min_max_avg", "unit": "m",
                "label": "Установка труб канализации"}
        result = match_quote([["Установка труб канализации", "мин 100 MDL",
                               "макс 200 MDL", "в среднем 114 MDL", "Все цены"]], rule)
        self.assertEqual(result["reason"], "unit_mismatch")

    def test_topmaster_bad_column_order_or_averages_rejected(self):
        rule = {"format": "topmaster_min_max_avg", "unit": "m",
                "label": "Установка труб канализации м/п"}
        invalid_rows = [
            ["Установка труб канализации м/п", "мин 100 MDL",
             "макс 200 MDL", "в среднем 240 MDL", "Все цены"],
            ["Установка труб канализации м/п", "макс 100 MDL",
             "мин 200 MDL", "в среднем 114 MDL", "Все цены"],
            ["Установка труб канализации м/п", "мин 100 MDL",
             "макс 200 MDL", "в среднем 114 MDL", "Реклама"],
        ]
        for invalid in invalid_rows:
            self.assertEqual(match_quote([invalid], rule)["status"], "rejected")

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
    def test_expanded_rules_include_all_pilot_mappings_and_are_allowlisted(self):
        _, sources, doc = fixtures()
        rules = validate_rules(doc, sources)
        self.assertEqual(len(rules), 51)
        self.assertEqual(len({r["workKey"] for r in rules}), 35)
        self.assertEqual(len({r["workKey"] for r in rules if r["workKey"] != "startPuttyWork"}), 34)
        self.assertEqual(len(rules[:14]), 14)

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

    def test_topmaster_format_and_url_bound_together(self):
        _, sources, doc = fixtures()
        unsafe = copy.deepcopy(doc)
        entry = next(r for r in unsafe["rules"] if r["url"] == TOPMASTER)
        entry["format"] = "single_price"
        with self.assertRaisesRegex(ValueError, "Topmaster format"):
            validate_rules(unsafe, sources)
        unsafe = copy.deepcopy(doc)
        entry = next(r for r in unsafe["rules"] if r["url"] == TOPMASTER)
        entry["url"] = CONSTRUCT
        with self.assertRaisesRegex(ValueError, "Topmaster format"):
            validate_rules(unsafe, sources)

    def test_unchanged_catalog_sources_and_rules(self):
        catalog, sources, doc = fixtures()
        before = copy.deepcopy((catalog, sources, doc))
        pilot_doc = {**doc, "rules": doc["rules"][:14]}
        collect(catalog, sources, pilot_doc, NOW,
                fetcher=lambda url: {REMONT: REMONT_HTML,
                                     CONSTRUCT: CONSTRUCT_HTML,
                                     EXPERT: EXPERT_HTML}[url])
        self.assertEqual((catalog, sources, doc), before)

    def test_new_mapping_does_not_accept_other_unit_or_unapproved_source(self):
        _, sources, doc = fixtures()
        building = [r for r in validate_rules(doc, sources) if r["url"] == BUILDING]
        self.assertEqual(len(building), 15)
        self.assertTrue(any(r["workKey"] == "electricalCableLayWork" for r in building))
        self.assertTrue(any(r["workKey"] == "removeWallpaperWork" for r in building))

    def test_actual_source_unit_errors_cannot_be_turned_into_prices(self):
        _, sources, doc = fixtures()
        rules = validate_rules(doc, sources)
        for key, label, source_unit in (
            ("skirtingWork", "Монтаж плинтусов м/п", ""),
            ("electricalCableLayWork", "Прокладка кабеля в ПВХ трубе м/п", "buc."),
        ):
            rule = next(r for r in rules if r["workKey"] == key and r["url"] == BUILDING)
            found = match_quote([[label, "10", "20", "50", source_unit, "→"]], rule)
            self.assertEqual(found, {"status": "rejected", "reason": "unit_mismatch"})

    def test_extended_exact_table_research_remains_unpublished(self):
        catalog, sources, doc = fixtures()
        pages = {
            REMONT: REMONT_HTML + "<table>" + row(
                "Шпатлёвка потолока под покраску кв.м", "30", "45", "70", "m²", "→")
                + row("Покраска потолок Кв.м", "30", "40", "65", "m²", "→")
                + row("Грунтовка потолков м2", "10", "15", "25", "m²", "→")
                + row("Укладка плитки на стены, от 20 до 60 см кв.м", "110", "165", "240", "m²", "→") + "</table>",
            CONSTRUCT: CONSTRUCT_HTML + "<table>" + row("Настил ламината", "м2", "100")
                + row("Монтаж напольного плинтуса", "м.п.", "48")
                + row("Нанесение декоративной штукатурки (2 цвета и более)", "м2", "280")
                + "</table>",
            EXPERT: EXPERT_HTML,
            BUILDING: "<table>" + row("Снятие обоев м2", "25", "38", "40", "m²", "→")
                + row("Устройство наливных полов м2", "50", "120", "200", "m²", "→")
                + row("Установка подразетников шт", "25", "60", "160", "buc.", "→")
                + row("Монтаж плинтусов м/п", "25", "70", "140", "", "→") + "</table>",
            ELECTRIC: "<table>" + row("Демонтаж розеток и выключателей шт",
                                          "30", "50", "80", "buc.", "→") + "</table>",
            TILING: "<table>" + row("Грунтовка стяжки под плитку кв.м.",
                                      "10", "18", "30", "m²", "→")
                + row("Укладка настенной плитки, длинна и ширина до 40 см кв.м",
                      "120", "180", "300", "m²", "→")
                + row("Укладка напольной плитки длина и ширина до 40 см кв.м",
                      "100", "160", "280", "m²", "→") + "</table>",
            TOPMASTER: "<table>" + row("Установка труб в/с м/п", "мин 30 MDL",
                                         "макс 100 MDL", "в среднем 90 MDL", "Все цены")
                + row("Установка труб канализации м/п", "мин 100 MDL",
                      "макс 200 MDL", "в среднем 114 MDL", "Все цены") + "</table>",
        }
        pages[EURO] = "<table>" + row(
            "Монтаж провода в гофру", "м", "от 20"
        ) + row(
            "Установка плинтуса", "м", "от 50"
        ) + "</table>"
        report = collect(catalog, sources, doc, NOW, fetcher=lambda url: pages[url])
        self.assertEqual(report["summary"]["workTypesInPilot"], 35)
        self.assertEqual(report["summary"]["mappedSourceWorkPairs"], 51)
        self.assertEqual(report["summary"]["catalogLaborRates"], 37)
        self.assertEqual(report["summary"]["quoteRowsRejectedByUnit"], 1)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertEqual(report["summary"]["publicationReadyLaborRates"], 0)
        quotes = [o for o in report["observations"] if o["status"] == "research_quote"]
        self.assertTrue(any(o["workKey"] == "removeWallpaperWork" and
                            o["minimumMDL"] == 25 for o in quotes))
        self.assertTrue(any(o["workKey"] == "laminateWork" and
                            o["minimumMDL"] == 100 for o in quotes))
        self.assertTrue(any(o["workKey"] == "plumbingSewerPipeWork" and
                            o["minimumMDL"] == 100 and
                            o["maximumMDL"] == 200 for o in quotes))
        self.assertTrue(all(o["scopeStatus"] == "review_required"
                            for o in quotes if o["source"] == "topmaster.md"))
        self.assertTrue(all(not o["priceDateVerified"] and
                            not o["approvedForPublication"] for o in quotes))



class Stage23ResearchTests(unittest.TestCase):
    def test_exact_meter_source_is_allowlisted(self):
        _, sources, doc = fixtures()
        entries = [
            rule for rule in validate_rules(doc, sources)
            if rule["url"] == EURO
        ]
        self.assertEqual(len(entries), 2)
        self.assertEqual(
            {item["workKey"] for item in entries},
            {"electricalCableLayWork", "skirtingWork"}
        )
        self.assertTrue(all(item["unit"] == "m" for item in entries))
        self.assertTrue(all(
            item["scope"] == "review_required" for item in entries
        ))

    def test_lower_bounds_are_not_verified_rates(self):
        _, sources, doc = fixtures()
        entries = [
            rule for rule in validate_rules(doc, sources)
            if rule["url"] == EURO
        ]
        rows = [
            ["Монтаж провода в гофру", "м", "от 20"],
            ["Установка плинтуса", "м", "от 50"],
        ]
        for rule in entries:
            result = match_quote(rows, rule)
            self.assertEqual(result["status"], "research_quote")
            self.assertEqual(result["priceKind"], "lower_bound")
            self.assertEqual(result["unit"], "m")
            self.assertIsNone(result["maximumMDL"])

    def test_wrong_unit_and_different_technology_fail_closed(self):
        rule = {
            "label": "Монтаж провода в гофру",
            "unit": "m",
            "format": "single_price"
        }
        incorrect = match_quote(
            [["Монтаж провода в гофру", "шт", "от 20"]],
            rule
        )
        self.assertEqual(incorrect["reason"], "unit_mismatch")

        wrong_job = match_quote(
            [["Монтаж провода без гофры", "м", "от 20"]],
            rule
        )
        self.assertEqual(wrong_job["status"], "not_found")

    def test_new_quotes_never_enable_publication(self):
        catalog, sources, doc = fixtures()
        selected = {
            **doc,
            "rules": [
                rule for rule in doc["rules"]
                if rule["url"] == EURO
            ]
        }
        html = (
            "<table>"
            + row("Монтаж провода в гофру", "м", "от 20")
            + row("Установка плинтуса", "м", "от 50")
            + "</table>"
        )
        report = collect(
            catalog, sources, selected, NOW,
            fetcher=lambda _: html
        )
        self.assertEqual(report["summary"]["quoteRowsExtracted"], 2)
        self.assertEqual(report["summary"]["publicationReadyLaborRates"], 0)
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["automaticLaborPublicationEnabled"])
        self.assertTrue(all(
            not item["approvedForPublication"]
            and not item["priceDateVerified"]
            for item in report["observations"]
        ))


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
