"""Offline safety tests for COSTARO stage 24 evidence dossiers."""

import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_labor_prices import load
from audit_live_labor_drift import audit as audit_drift
from build_labor_review_queue import build_queue
from build_labor_evidence_dossiers import build_dossiers, render_markdown
from collect_live_labor_quotes import collect


def fixtures(include_lower_bound=True):
    catalog = load(ROOT / "prices.json")
    sources = load(ROOT / "labor_market_sources.json")
    rules = load(ROOT / "labor_live_match_rules.json")
    leads = load(ROOT / "labor_manual_research_leads.json")

    def fetcher(url):
        if (
            include_lower_bound
            and url == "https://euroremontstyle.md/remont-kvartir-ceny"
        ):
            return (
                "<table><tr>"
                "<td>Монтаж провода в гофру</td>"
                "<td>м</td>"
                "<td>от 20</td>"
                "</tr></table>"
            )

        if url == "https://construct.md/ru/pages/price/":
            return (
                "<table><tr>"
                "<td>Поклейка обоев на стены</td>"
                "<td>м2</td>"
                "<td>45</td>"
                "</tr></table>"
            )

        return "<html><table></table></html>"

    live = collect(
        catalog,
        sources,
        rules,
        datetime(2026, 11, 3, tzinfo=timezone.utc),
        fetcher=fetcher,
    )

    drift = audit_drift(catalog, live)

    queue = build_queue(
        catalog, sources, rules, live, drift, leads
    )

    return catalog, sources, rules, live, drift, leads, queue


class LaborEvidenceDossierTests(unittest.TestCase):

    def test_all_38_works_and_51_observations(self):
        report = build_dossiers(*fixtures())
        summary = report["summary"]

        self.assertEqual(summary["workTypesReviewed"], 38)
        self.assertEqual(summary["workTypesWithExactMappings"], 35)
        self.assertEqual(summary["workTypesWithoutExactMappings"], 3)
        self.assertEqual(summary["technologySpecificManualLeads"], 5)
        self.assertEqual(summary["sourceObservations"], 53)
        self.assertEqual(len(report["dossiers"]), 38)

        self.assertEqual(summary["publicationReadyLaborRates"], 0)
        self.assertFalse(report["automaticLaborPublicationEnabled"])
        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])

        self.assertTrue(all(
            not row["approvedForPublication"]
            and not row["priceDateVerified"]
            for row in report["dossiers"]
        ))

    def test_lower_bound_is_not_a_fixed_tariff(self):
        report = build_dossiers(*fixtures())

        cable = next(
            row for row in report["dossiers"]
            if row["workKey"] == "electricalCableLayWork"
        )

        quotes = [
            entry["researchQuote"]
            for entry in cable["evidenceRows"]
            if entry["researchQuote"] is not None
        ]

        self.assertTrue(any(
            quote["kind"] == "lower_bound"
            and quote["minimumMDL"] == 20.0
            and "maximumMDL" not in quote
            for quote in quotes
        ))

        markdown = render_markdown(report)

        self.assertIn("от 20.0 MDL/пог. м", markdown)
        self.assertIn("Подтверждено к публикации: **0**", markdown)

    def test_three_unmapped_categories_remain_research_only(self):
        report = build_dossiers(*fixtures())

        missing = {
            row["workKey"]
            for row in report["dossiers"]
            if row["reviewGroup"] == "no_exact_mapping"
        }

        self.assertEqual(missing, {
            "floorRemoveOtherWork",
            "removeDecorativeWork",
            "vinylWork",
        })

        for row in report["dossiers"]:
            if row["workKey"] in missing:
                self.assertEqual(row["evidenceRows"], [])
                self.assertTrue(row["manualLeads"])
                self.assertFalse(row["approvedForPublication"])

    def test_tampered_manual_queue_is_rejected(self):
        data = list(fixtures())

        data[-1] = copy.deepcopy(data[-1])
        data[-1]["workReview"][0]["approvedForPublication"] = True

        with self.assertRaises(ValueError):
            build_dossiers(*data)

    def test_missing_queue_entry_is_rejected(self):
        data = list(fixtures())

        data[-1] = copy.deepcopy(data[-1])
        data[-1]["workReview"].pop()

        with self.assertRaises(ValueError):
            build_dossiers(*data)

    def test_modified_source_observation_is_rejected(self):
        data = list(fixtures())

        data[3] = copy.deepcopy(data[3])
        data[3]["observations"][0]["priceDateVerified"] = True

        with self.assertRaises(ValueError):
            build_dossiers(*data)

    def test_markdown_escapes_unsafe_text(self):
        report = build_dossiers(*fixtures())

        report["dossiers"][0]["workKey"] = "<script>|test"

        markdown = render_markdown(report)

        self.assertNotIn("<script>", markdown)
        self.assertIn("&lt;script&gt;", markdown)
        self.assertIn(r"\|", markdown)

    def test_report_is_read_only_for_input_data(self):
        data = fixtures()
        original = copy.deepcopy(data)

        build_dossiers(*data)

        self.assertEqual(data, original)

    def test_no_live_quotes_still_produces_safe_report(self):
        report = build_dossiers(*fixtures(include_lower_bound=False))

        self.assertEqual(report["summary"]["workTypesReviewed"], 38)
        self.assertEqual(report["summary"]["sourceObservations"], 53)
        self.assertEqual(report["summary"]["publicationReadyLaborRates"], 0)
        self.assertEqual(report["summary"]["lowerBoundQuotes"], 0)


if __name__ == "__main__":
    unittest.main()