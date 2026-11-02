"""Offline safety and provisional comparison tests for labor drift screening."""

import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_labor_prices import load
from audit_live_labor_drift import audit
from collect_live_labor_quotes import collect


ROOT = Path(__file__).resolve().parents[1]
REMONT = "https://remont.md/ru/preturi/clerical/facing/"
CONSTRUCT = "https://construct.md/ru/pages/price/"
EXPERT = "https://remontexpert.md/service/tencuitor-zugrav/"
BUILDING = "https://remont.md/ru/preturi/clerical/building_installation_work/"


def row(*values):
    return "<tr>" + "".join(f"<td>{v}</td>" for v in values) + "</tr>"


def sample():
    catalog = load(ROOT / "prices.json")
    sources = load(ROOT / "labor_market_sources.json")
    rules = load(ROOT / "labor_live_match_rules.json")
    rules = {**rules, "rules": rules["rules"][:14] + [r for r in rules["rules"][14:]
                                                   if r["workKey"] in {
                                                       "skirtingWork", "electricalCableLayWork"
                                                   } and r["url"] == BUILDING]}
    pages = {
        REMONT: "<table>" + row("Поклейка обоев на стены кв.м", "30", "45", "80", "m²", "→")
            + row("Монтаж гипсокартона на потолок кв.м", "80", "140", "200", "m²", "→")
            + row("Покраска стен кв.м", "22", "35", "70", "m²", "→") + "</table>",
        CONSTRUCT: "<table>" + row("Поклейка обоев на стены", "м2", "45")
            + row("Монтаж гипсокартона на потолок", "м2", "170")
            + row("Покраска стен", "м2", "45") + "</table>",
        EXPERT: "<table>" + row("Покраска стен, 2 слоя", "м²", "от 80") + "</table>",
        BUILDING: "<table>" + row("Монтаж плинтусов м/п", "25", "70", "140", "", "→")
            + row("Прокладка кабеля в ПВХ трубе м/п", "10", "20", "50", "buc.", "→")
            + "</table>",
    }
    report = collect(catalog, sources, rules, datetime(2026, 11, 2, tzinfo=timezone.utc),
                     fetcher=lambda url: pages[url])
    return catalog, report


class DriftReportTests(unittest.TestCase):
    def test_all_37_and_optional_stage_reported_and_prices_preserved(self):
        catalog, live = sample()
        snapshot = copy.deepcopy((catalog, live))
        result = audit(catalog, live)
        self.assertEqual((catalog, live), snapshot)
        self.assertEqual(result["summary"]["catalogLaborRates"], 37)
        self.assertEqual(result["summary"]["laborRatesReviewed"], 38)
        self.assertEqual(result["summary"]["insidePreliminaryBandNotVerified"], 2)
        self.assertEqual(result["summary"]["rejectedUnitRows"], 2)
        self.assertEqual(result["summary"]["approvedForPublication"], 0)
        self.assertFalse(result["publishedPricesChanged"])
        self.assertFalse(result["flutterCalculationsChanged"])
        self.assertFalse(result["automaticLaborPublicationEnabled"])
        self.assertTrue(all(not r["approvedForPublication"] and
                            not r["priceDateVerified"] for r in result["workReview"]))

    def test_two_bounded_independent_domains_only_qualify_for_screening(self):
        catalog, live = sample()
        result = audit(catalog, live)
        rows = {r["workKey"]: r for r in result["workReview"]}
        self.assertEqual(rows["wallpaperWork"]["boundedAlignedIndependentDomains"], 2)
        self.assertEqual(rows["wallpaperWork"]["marketBandResearchOnly"]["provisionalMinimumMDL"], 30)
        self.assertEqual(rows["wallpaperWork"]["marketBandResearchOnly"]["provisionalMaximumMDL"], 80)
        self.assertEqual(rows["wallPaintWork"]["screeningStatus"], "not_comparable")
        self.assertEqual(rows["wallPaintWork"]["lowerBoundsExcluded"], 1)
        self.assertEqual(rows["plasterWork"]["screeningStatus"], "not_comparable")
        self.assertEqual(rows["skirtingWork"]["screeningStatus"], "not_comparable")

    def test_outside_price_band_triggers_manual_review_only(self):
        catalog, live = sample()
        target = [o for o in live["observations"] if o["workKey"] == "wallpaperWork"]
        self.assertEqual(len(target), 2)
        for quote in target:
            quote["minimumMDL"] = 250
            quote["maximumMDL"] = 280 if quote["priceKind"] == "range_with_average" else 250
        result = audit(catalog, live)
        row_ = next(r for r in result["workReview"] if r["workKey"] == "wallpaperWork")
        self.assertEqual(row_["screeningStatus"], "outside_preliminary_band_manual_review")
        self.assertEqual(result["summary"]["outsidePreliminaryBandManualReview"], 1)
        self.assertEqual(catalog["laborPrices"]["wallpaperWork"]["standard"], 45)
        self.assertFalse(result["publishedPricesChanged"])

    def test_two_rows_on_one_host_do_not_become_two_domains(self):
        catalog, live = sample()
        target = next(o for o in live["observations"] if o["workKey"] == "wallpaperWork"
                      and o["source"] == "construct.md")
        target["url"] = BUILDING
        target["source"] = "remont.md"
        result = audit(catalog, live)
        row_ = next(r for r in result["workReview"] if r["workKey"] == "wallpaperWork")
        self.assertEqual(row_["screeningStatus"], "insufficient_independent_sources")

    def test_lower_bounds_and_scope_mismatches_do_not_qualify(self):
        catalog, live = sample()
        result = audit(catalog, live)
        rows = {r["workKey"]: r for r in result["workReview"]}
        self.assertEqual(rows["wallPaintWork"]["boundedAlignedIndependentDomains"], 0)
        self.assertEqual(rows["wallPaintWork"]["quotesNeedingScopeReview"], 2)
        self.assertEqual(rows["wallPaintWork"]["lowerBoundsExcluded"], 1)

    def test_publication_boolean_or_catalog_version_tamper_rejected(self):
        catalog, live = sample()
        for path, value in (("automaticLaborPublicationEnabled", True),
                            ("publishedPricesChanged", True),
                            ("catalogVersion", "99.0.0")):
            poisoned = copy.deepcopy(live)
            poisoned[path] = value
            with self.assertRaisesRegex(ValueError, "Unsafe"):
                audit(catalog, poisoned)

    def test_quote_publication_or_verified_date_tamper_rejected(self):
        catalog, live = sample()
        for field in ("approvedForPublication", "priceDateVerified"):
            poisoned = copy.deepcopy(live)
            poisoned["observations"][0][field] = True
            with self.assertRaisesRegex(ValueError, "publication-enabled"):
                audit(catalog, poisoned)

    def test_wrong_host_for_url_and_duplicate_rows_rejected(self):
        catalog, live = sample()
        poisoned = copy.deepcopy(live)
        poisoned["observations"][0]["source"] = "another.md"
        with self.assertRaisesRegex(ValueError, "Invalid or publication-enabled"):
            audit(catalog, poisoned)
        poisoned = copy.deepcopy(live)
        poisoned["observations"].append(copy.deepcopy(poisoned["observations"][0]))
        poisoned["summary"]["mappedSourceWorkPairs"] += 1
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            audit(catalog, poisoned)

    def test_malformed_bound_and_invalid_unmatched_price_rejected(self):
        catalog, live = sample()
        found = next(i for i, o in enumerate(live["observations"])
                     if o["status"] == "research_quote")
        poisoned = copy.deepcopy(live)
        poisoned["observations"][found]["maximumMDL"] = -50
        with self.assertRaisesRegex(ValueError, "Malformed"):
            audit(catalog, poisoned)
        rejected = next(i for i, o in enumerate(live["observations"])
                        if o["status"] == "rejected")
        poisoned = copy.deepcopy(live)
        poisoned["observations"][rejected]["minimumMDL"] = 123
        with self.assertRaisesRegex(ValueError, "Unmatched"):
            audit(catalog, poisoned)


if __name__ == "__main__":
    unittest.main()
