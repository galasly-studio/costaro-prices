"""Offline fail-closed checks for 38-work COSTARO manual research queue."""

import copy
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_labor_prices import load
from audit_live_labor_drift import audit as audit_drift
from build_labor_review_queue import build_queue, check_leads
from collect_live_labor_quotes import collect


ROOT = Path(__file__).resolve().parents[1]


def fixtures():
    catalog = load(ROOT / "prices.json")
    sources = load(ROOT / "labor_market_sources.json")
    rules = load(ROOT / "labor_live_match_rules.json")
    leads = load(ROOT / "labor_manual_research_leads.json")

    def fetcher(url):
        if url == "https://construct.md/ru/pages/price/":
            return ("<table><tr><td>Поклейка обоев на стены</td>"
                    "<td>м2</td><td>45</td></tr></table>")
        if url == "https://remont.md/ru/preturi/clerical/facing/":
            return ("<table><tr><td>Поклейка обоев на стены кв.м</td>"
                    "<td>30</td><td>45</td><td>80</td><td>m²</td>"
                    "<td>→</td></tr></table>")
        return "<html><table></table></html>"

    live = collect(catalog, sources, rules,
                   datetime(2026, 11, 3, tzinfo=timezone.utc), fetcher=fetcher)
    return catalog, sources, rules, live, audit_drift(catalog, live), leads


class ManualQueueTests(unittest.TestCase):
    def test_38_work_queue_and_three_unmapped_technologies(self):
        result = build_queue(*fixtures())
        summary = result["summary"]
        self.assertEqual(summary["catalogLaborRates"], 37)
        self.assertEqual(summary["workTypesReviewed"], 38)
        self.assertEqual(summary["workTypesWithExactMappings"], 35)
        self.assertEqual(summary["workTypesWithoutExactMappings"], 3)
        self.assertEqual(summary["manualLeadsForUnmappedWork"], 5)
        unmapped = {r["workKey"] for r in result["workReview"]
                    if r["reviewGroup"] == "no_exact_mapping"}
        self.assertEqual(unmapped, {
            "removeDecorativeWork", "floorRemoveOtherWork", "vinylWork"})
        self.assertEqual(summary["publicationReadyLaborRates"], 0)
        self.assertFalse(result["automaticLaborPublicationEnabled"])
        self.assertFalse(result["publishedPricesChanged"])
        self.assertFalse(result["flutterCalculationsChanged"])
        self.assertTrue(all(not r["approvedForPublication"]
                            and not r["priceDateVerified"]
                            for r in result["workReview"]))

    def test_preliminary_two_site_quote_is_never_approved(self):
        report = build_queue(*fixtures())
        wallpaper = next(r for r in report["workReview"]
                         if r["workKey"] == "wallpaperWork")
        self.assertEqual(wallpaper["reviewGroup"], "preliminary_comparison_only")
        self.assertEqual(wallpaper["comparableBoundedIndependentSites"], 2)
        self.assertFalse(wallpaper["approvedForPublication"])

    def test_all_manual_leads_scope_limited_no_prices(self):
        *_, leads = fixtures()
        mapping = check_leads(leads, {
            "removeDecorativeWork", "floorRemoveOtherWork", "vinylWork"})
        self.assertEqual([len(mapping[k]) for k in (
            "removeDecorativeWork", "floorRemoveOtherWork", "vinylWork")], [1, 2, 2])
        for items in mapping.values():
            for lead in items:
                self.assertNotIn("price", " ".join(lead.keys()).lower())
                self.assertFalse(lead["approvedForPublication"])

    def test_wrong_manual_domain_or_unauthorized_price_rejected(self):
        data = fixtures()
        tampered = copy.deepcopy(data)
        tampered[-1]["leads"][0]["url"] = "https://example.org/price"
        with self.assertRaisesRegex(ValueError, "approved research URL"):
            build_queue(*tampered)
        tampered = copy.deepcopy(data)
        tampered[-1]["leads"][0]["priceMDL"] = 60
        with self.assertRaisesRegex(ValueError, "price-bearing"):
            build_queue(*tampered)

    def test_unknown_work_or_missing_manual_technology_rejected(self):
        data = fixtures()
        tampered = copy.deepcopy(data)
        tampered[-1]["leads"][0]["workKey"] = "wallpaperWork"
        with self.assertRaisesRegex(ValueError, "unmapped key"):
            build_queue(*tampered)
        tampered = copy.deepcopy(data)
        tampered[-1]["leads"] = [x for x in tampered[-1]["leads"]
                                  if x["workKey"] != "vinylWork"]
        with self.assertRaisesRegex(ValueError, "All and only unmapped"):
            build_queue(*tampered)

    def test_publication_flag_or_bad_unit_rejected(self):
        data = fixtures()
        tampered = copy.deepcopy(data)
        tampered[-1]["publicationAllowed"] = True
        with self.assertRaisesRegex(ValueError, "Unsafe manual"):
            build_queue(*tampered)
        tampered = copy.deepcopy(data)
        tampered[-1]["leads"][0]["unit"] = "piece"
        with self.assertRaisesRegex(ValueError, "incomplete manual lead"):
            build_queue(*tampered)

    def test_quote_or_drift_tampering_rejected(self):
        data = fixtures()
        tampered = copy.deepcopy(data)
        tampered[3]["observations"][0]["expectedLabel"] = "Fictional label"
        with self.assertRaisesRegex(ValueError, "pinned exact rule"):
            build_queue(*tampered)
        tampered = copy.deepcopy(data)
        tampered[4]["workReview"][0]["screeningStatus"] = "price_verified"
        with self.assertRaisesRegex(ValueError, "altered or is inconsistent"):
            build_queue(*tampered)

    def test_adding_exact_mapping_demands_removing_old_lead(self):
        data = fixtures()
        tampered = list(copy.deepcopy(data))
        rule = copy.deepcopy(tampered[2]["rules"][0])
        rule["workKey"] = "removeDecorativeWork"
        rule["label"] = "Демонтаж декоративного покрытия стен"
        rule["scope"] = "review_required"
        tampered[2]["rules"].append(rule)
        # Keep observation bookkeeping consistent; leads must still be retired.
        tampered[3] = collect(tampered[0], tampered[1], tampered[2],
                              datetime(2026, 11, 3, tzinfo=timezone.utc),
                              fetcher=lambda _: "<table></table>")
        tampered[4] = audit_drift(tampered[0], tampered[3])
        with self.assertRaisesRegex(ValueError, "unmapped key"):
            build_queue(*tampered)

    def test_build_queue_is_read_only_for_all_inputs(self):
        data = fixtures()
        before = copy.deepcopy(data)
        build_queue(*data)
        self.assertEqual(data, before)


if __name__ == "__main__":
    unittest.main()
