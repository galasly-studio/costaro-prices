# COSTARO stage 26 — offline source safety tests.

from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audit_labor_prices import load
from audit_live_labor_drift import audit
from check_labor_source_health import validate_url
from collect_live_labor_quotes import (
    collect,
    match_quote,
    normalized_unit,
    parse_two_point_range,
    validate_rules,
)

CABLE = "https://electricchisinau.md/"
PVC = "https://lumeamesterilor.md/ru/styazhka-pola/"


class Stage26Tests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.catalog = load(ROOT / "prices.json")
        cls.sources = load(ROOT / "labor_market_sources.json")
        cls.doc = load(ROOT / "labor_live_match_rules.json")
        cls.rules = [
            rule
            for rule in validate_rules(cls.doc, cls.sources)
            if rule["url"] in (CABLE, PVC)
        ]

    def test_exact_sources_and_work_types(self):
        self.assertEqual(len(self.rules), 2)
        self.assertEqual(
            {r["workKey"] for r in self.rules},
            {"electricalCableLayWork", "skirtingWork"},
        )
        self.assertEqual(validate_url(CABLE), "electricchisinau.md")
        self.assertEqual(validate_url(PVC), "lumeamesterilor.md")
        self.assertTrue(
            all(
                r["scope"] == "review_required"
                and r["unit"] == "m"
                for r in self.rules
            )
        )

    def test_range_has_no_invented_average(self):
        self.assertEqual(parse_two_point_range("20 - 30"), (20, 30))
        self.assertEqual(parse_two_point_range("20–30 MDL"), (20, 30))
        self.assertEqual(normalized_unit("Per metru liniar"), "m")

        for value in (
            "от 20", "20", "20 - 20", "30 - 20",
            "0 - 30", "20 - 30 EUR", "20 - 99999",
        ):
            self.assertIsNone(parse_two_point_range(value))

    def test_wrong_units_and_labels_are_rejected(self):
        cable = next(r for r in self.rules if r["url"] == CABLE)

        valid = match_quote(
            [[
                "Pozare cablu (fără șanț / pe tavan)",
                "Per metru liniar",
                "20 - 30",
            ]],
            cable,
        )

        self.assertEqual(valid["status"], "research_quote")
        self.assertEqual(valid["priceKind"], "range_without_average")
        self.assertNotIn("averageMDL", valid)

        wrong_unit = match_quote(
            [[
                "Pozare cablu (fără șanț / pe tavan)",
                "buc.",
                "20 - 30",
            ]],
            cable,
        )

        self.assertEqual(wrong_unit["reason"], "unit_mismatch")

        wrong_job = match_quote(
            [["Pozare cablu în șanț", "Per metru liniar", "20 - 30"]],
            cable,
        )

        self.assertEqual(wrong_job["status"], "not_found")

    def test_new_sources_never_publish_prices(self):
        selected = {**self.doc, "rules": self.rules}

        pages = {
            CABLE: (
                "<table><tr>"
                "<td>Pozare cablu (fără șanț / pe tavan)</td>"
                "<td>Per metru liniar</td>"
                "<td>20 - 30</td>"
                "</tr></table>"
            ),
            PVC: (
                "<table><tr>"
                "<td>Монтаж ПВХ-плинтуса</td>"
                "<td>м.п.</td>"
                "<td>45</td>"
                "</tr></table>"
            ),
        }

        report = collect(
            self.catalog,
            self.sources,
            selected,
            datetime(2026, 11, 3, tzinfo=timezone.utc),
            fetcher=lambda url: pages[url],
        )

        self.assertEqual(report["summary"]["mappedSourceWorkPairs"], 2)
        self.assertEqual(report["summary"]["quoteRowsExtracted"], 2)
        self.assertEqual(report["summary"]["publicationReadyLaborRates"], 0)

        self.assertFalse(report["publishedPricesChanged"])
        self.assertFalse(report["flutterCalculationsChanged"])
        self.assertFalse(report["automaticLaborPublicationEnabled"])

        for row in report["observations"]:
            self.assertFalse(row["priceDateVerified"])
            self.assertFalse(row["approvedForPublication"])
            self.assertEqual(row["scopeStatus"], "review_required")

        result = audit(self.catalog, report)

        self.assertEqual(result["summary"]["approvedForPublication"], 0)
        self.assertFalse(result["publishedPricesChanged"])


if __name__ == "__main__":
    unittest.main()
