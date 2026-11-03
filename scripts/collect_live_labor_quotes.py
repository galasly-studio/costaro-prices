#!/usr/bin/env python3
"""Read-only, scope-aware research extraction of Moldova labor quotes.

Only exact, predefined HTML table rows may produce a quote. Neither a quote
nor two matching sites approves a COSTARO budget/standard/premium rate.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
import unicodedata
import urllib.request

from audit_labor_prices import LABOR_KEYS, catalog_errors, load, required_unit
from check_labor_source_health import (
    OnlyApprovedRedirects, error_category, looks_like_block_page, validate_url,
)


from labor_network_retry import open_with_guarded_retry

MAX_HTML_BYTES = 2_000_000
KINDS = frozenset({"min_avg_max", "single_price", "topmaster_min_max_avg"})
SCOPES = frozenset({"preliminarily_aligned", "review_required"})
PRICE = re.compile(r"^(от\s+)?(\d{1,4}(?:[.,]\d{1,2})?)\s*(?:mdl|лей|lei)?$", re.I)
EXACT_KEYS = frozenset(LABOR_KEYS) | {"startPuttyWork"}
TOPMASTER_CATEGORY = "https://topmaster.md/price/montazhnyje-raboty-po-santehnike/"
# Additional HTML pages are allowed for this research ONLY, not approved as
# stored market benchmarks and not added to labor_market_sources.json.
EXTRA_RESEARCH_PAGES = frozenset({
    "https://remont.md/ru/preturi/clerical/tiling/",
    TOPMASTER_CATEGORY,
    "https://euroremontstyle.md/remont-kvartir-ceny",
})
TOPMASTER_AMOUNT = re.compile(r"^(мин|макс|в среднем)\s+(\d{1,4}(?:[.,]\d{1,2})?)\s+MDL$", re.I)


def normalize_label(value: str) -> str:
    text = unicodedata.normalize("NFKC", value).casefold().replace("ё", "е")
    return re.sub(r"\s+", " ", re.sub(r"[^\w]+", " ", text)).strip()


def normalized_unit(value: str) -> str | None:
    text = unicodedata.normalize("NFKC", value).casefold()
    text = re.sub(r"[\s.]+", "", text).replace("²", "2")
    if text in {"m2", "м2", "квм", "квм2", "квметр"}:
        return "m2"
    if text in {"м", "m", "пм", "мп", "мпог", "ml", "мл"}:
        return "m"
    if text in {"шт", "buc", "piece", "unitate"}:
        return "piece"
    return None


def parse_value(value: str) -> tuple[float, bool] | None:
    text = unicodedata.normalize("NFKC", value).casefold().strip()
    text = re.sub(r"\s+", " ", text.replace("\xa0", " "))
    match = PRICE.fullmatch(text)
    if not match:
        return None
    amount = round(float(match.group(2).replace(",", ".")), 2)
    if not 1 <= amount <= 3000:
        return None
    return amount, bool(match.group(1))


def parse_topmaster_amount(value: str, expected_prefix: str) -> float | None:
    """Strictly parse one clearly labelled, MDL-denominated category price."""
    match = TOPMASTER_AMOUNT.fullmatch(" ".join(value.split()))
    if not match or match.group(1).casefold() != expected_prefix:
        return None
    parsed = parse_value(match.group(2))
    return parsed[0] if parsed is not None and not parsed[1] else None


class StrictTableRows(HTMLParser):
    """Read data cells only from HTML table rows; ignore page marketing prices."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self.in_row = False
        self.in_cell = False
        self.ignored_depth = 0
        self.cells: list[str] = []
        self.cell_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style"):
            self.ignored_depth += 1
        if self.ignored_depth:
            return
        if tag == "tr":
            self.in_row = True
            self.in_cell = False
            self.cells = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.cell_text = []

    def handle_data(self, data: str) -> None:
        if self.in_row and self.in_cell and not self.ignored_depth:
            self.cell_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style") and self.ignored_depth:
            self.ignored_depth -= 1
            return
        if self.ignored_depth:
            return
        if tag in ("td", "th") and self.in_row and self.in_cell:
            self.cells.append(" ".join("".join(self.cell_text).split()))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.cells:
                self.rows.append(self.cells)
            self.in_row = False
            self.in_cell = False


def html_rows(content: str) -> list[list[str]]:
    parser = StrictTableRows()
    parser.feed(content)
    parser.close()
    return parser.rows


def download_html(url: str) -> str:
    """Allowlisted HTTPS, guarded redirects, HTML only, strict size ceiling."""
    original_host = validate_url(url)
    request = urllib.request.Request(url, headers={
        "User-Agent": "COSTARO-LaborResearch/1.0",
        "Accept": "text/html",
    })
    opener = urllib.request.build_opener(OnlyApprovedRedirects())
    with open_with_guarded_retry(opener, request, timeout=15) as response:
        if validate_url(response.geturl()) != original_host:
            # A move to another approved domain is still a different source.
            # Counting both would falsely create two independent market quotes.
            raise ValueError("unapproved_redirect")
        if "text/html" not in response.headers.get("Content-Type", "").lower():
            raise ValueError("unexpected_content_type")
        body = response.read(MAX_HTML_BYTES + 1)
        if not body:
            raise ValueError("empty_response")
        if len(body) > MAX_HTML_BYTES:
            raise ValueError("response_too_large")
        return body.decode("utf-8", errors="replace")


def match_quote(rows: list[list[str]], rule: dict) -> dict:
    """Only one exactly named, unit-aligned row can yield research evidence."""
    matches = [row for row in rows if row and
               normalize_label(row[0]) == normalize_label(rule["label"])]
    if not matches:
        return {"status": "not_found", "reason": "exact_row_missing"}
    if len(matches) != 1:
        return {"status": "rejected", "reason": "duplicate_label_ambiguous"}
    row = matches[0]
    if rule["format"] == "topmaster_min_max_avg":
        # The unit is embedded in the exact service label, not a data column.
        # Do NOT interpret an offer priced by the connection/point as a meter.
        if len(row) != 5 or normalize_label(row[4]) != normalize_label("Все цены"):
            return {"status": "rejected", "reason": "unexpected_table_columns"}
        if not re.search(r"м\s*/\s*п\s*$", row[0], re.I) or rule["unit"] != "m":
            return {"status": "rejected", "reason": "unit_mismatch"}
        low = parse_topmaster_amount(row[1], "мин")
        high = parse_topmaster_amount(row[2], "макс")
        avg = parse_topmaster_amount(row[3], "в среднем")
        if any(price is None for price in (low, high, avg)) or not (low <= avg <= high):
            return {"status": "rejected", "reason": "invalid_min_avg_max"}
        return {"status": "research_quote", "reason": "exact_row_and_unit_match",
                "observedLabel": row[0], "unit": "m",
                "priceKind": "range_with_average", "minimumMDL": low,
                "averageMDL": avg, "maximumMDL": high}
    if rule["format"] == "min_avg_max":
        if len(row) not in (5, 6):
            return {"status": "rejected", "reason": "unexpected_table_columns"}
        unit_cell, raw_values = row[4], row[1:4]
    else:
        if len(row) != 3:
            return {"status": "rejected", "reason": "unexpected_table_columns"}
        unit_cell, raw_values = row[1], [row[2]]
    if normalized_unit(unit_cell) != rule["unit"]:
        return {"status": "rejected", "reason": "unit_mismatch"}

    prices = [parse_value(raw) for raw in raw_values]
    if any(value is None for value in prices):
        return {"status": "rejected", "reason": "invalid_or_unbounded_price"}
    values = [item[0] for item in prices]
    lower_bound = any(item[1] for item in prices)
    if rule["format"] == "min_avg_max":
        if lower_bound or not (values[0] <= values[1] <= values[2]):
            return {"status": "rejected", "reason": "invalid_min_avg_max"}
        evidence = {"priceKind": "range_with_average", "minimumMDL": values[0],
                    "averageMDL": values[1], "maximumMDL": values[2]}
    else:
        evidence = {"priceKind": "lower_bound" if lower_bound else "fixed_price",
                    "minimumMDL": values[0],
                    "maximumMDL": None if lower_bound else values[0]}
    return {"status": "research_quote", "reason": "exact_row_and_unit_match",
            "observedLabel": row[0], "unit": rule["unit"], **evidence}


def validate_rules(rules_doc: dict, source_doc: dict) -> list[dict]:
    if (rules_doc.get("schemaVersion") != 1 or rules_doc.get("market") != "MD"
            or rules_doc.get("currency") != "MDL"
            or rules_doc.get("publicationAllowed") is not False):
        raise ValueError("Invalid or publication-enabled live labor rules")
    items = rules_doc.get("rules")
    if not isinstance(items, list) or not items:
        raise ValueError("Rules must contain at least one exact mapping")
    source_map = source_doc.get("sources")
    if not isinstance(source_map, dict):
        raise ValueError("Labor market source map is missing")
    allowed_urls = {entry.get("url") for refs in source_map.values()
                    if isinstance(refs, list) for entry in refs
                    if isinstance(entry, dict) and isinstance(entry.get("url"), str)}
    allowed_urls |= EXTRA_RESEARCH_PAGES
    seen = set()
    for rule in items:
        if not isinstance(rule, dict) or set(rule) != {
            "workKey", "url", "format", "label", "unit", "scope", "scopeReason"
        }:
            raise ValueError("Unexpected rule schema")
        key = rule["workKey"]
        if (key not in EXACT_KEYS
                or rule["format"] not in KINDS or rule["scope"] not in SCOPES
                or rule["unit"] != required_unit(key)
                or not isinstance(rule["label"], str) or len(rule["label"]) < 12
                or not isinstance(rule["scopeReason"], str)
                or not re.fullmatch(r"[a-z0-9_]+", rule["scopeReason"])):
            raise ValueError(f"Unsafe or incompatible work mapping: {key}")
        validate_url(rule["url"])
        if rule["url"] not in allowed_urls:
            raise ValueError("Mapping points outside documented labor source URLs")
        if ((rule["format"] == "topmaster_min_max_avg") !=
                (rule["url"] == TOPMASTER_CATEGORY)):
            raise ValueError("Topmaster format must use its exact research page")
        if rule["format"] == "topmaster_min_max_avg" and rule["unit"] != "m":
            raise ValueError("Topmaster meter category cannot supply piece or m2 prices")
        identity = (key, rule["url"])
        if identity in seen:
            raise ValueError("Duplicate mapping for one work and URL")
        seen.add(identity)
    return items


def collect(catalog: dict, sources: dict, rules_doc: dict,
            checked_at: datetime, fetcher=download_html) -> dict:
    errors = catalog_errors(catalog)
    if errors:
        raise ValueError("Invalid catalog: " + "; ".join(errors))
    rules = validate_rules(rules_doc, sources)
    grouped: dict[str, list[dict]] = defaultdict(list)
    for rule in rules:
        grouped[rule["url"]].append(rule)

    host_blocked = {}
    source_results = {}
    observations = []
    for url in sorted(grouped):
        host = validate_url(url)
        if host in host_blocked:
            source_results[url] = {"status": "skipped", "reason":
                                   f"skipped_after_{host_blocked[host]}"}
            rows = None
        else:
            try:
                html = fetcher(url)
                if not isinstance(html, str):
                    raise ValueError("invalid_response")
                if looks_like_block_page(html):
                    source_results[url] = {"status": "blocked", "reason": "challenge_page"}
                    rows = None
                else:
                    rows = html_rows(html)
                    source_results[url] = {"status": "parsed", "reason": "html_table_read"}
            except (OSError, ValueError, UnicodeError) as error:
                reason = error_category(error)
                source_results[url] = {"status": "unavailable", "reason": reason}
                if reason in ("http_403", "http_429"):
                    host_blocked[host] = reason
                rows = None

        for rule in grouped[url]:
            result = ({"status": "not_checked", "reason": source_results[url]["reason"]}
                      if rows is None else match_quote(rows, rule))
            observations.append({
                "workKey": rule["workKey"],
                "source": host,
                "url": url,
                "expectedLabel": rule["label"],
                "expectedUnit": rule["unit"],
                "scopeStatus": rule["scope"],
                "scopeReason": rule["scopeReason"],
                "priceDateVerified": False,
                "approvedForPublication": False,
                **result,
            })

    by_work = defaultdict(list)
    for observation in observations:
        by_work[observation["workKey"]].append(observation)
    reviewed = []
    for key in sorted(by_work):
        quotes = [o for o in by_work[key] if o["status"] == "research_quote"]
        aligned = [o for o in quotes if o["scopeStatus"] == "preliminarily_aligned"]
        domains = {o["source"] for o in aligned}
        bounded = [o for o in aligned if o["maximumMDL"] is not None]
        bounds = {o["source"] for o in bounded}
        comparable = len(bounds) >= 2
        reviewed.append({
            "workKey": key,
            "quotesExtracted": len(quotes),
            "preliminarilyAlignedSources": len(domains),
            "boundedAlignedSources": len(bounds),
            "comparisonCandidateOnly": comparable,
            "candidateRangeMDL": (
                {"minimum": min(o["minimumMDL"] for o in bounded),
                 "maximum": max(o["maximumMDL"] for o in bounded)}
                if comparable else None
            ),
            "currentCatalogTiersMDL": (
                catalog["laborStagePrices"]["startPuttyWork"]
                if key == "startPuttyWork" and
                "startPuttyWork" in catalog.get("laborStagePrices", {})
                else catalog["laborPrices"].get(key)
            ),
            "needsHumanScopeAndDateReview": True,
            "approvedForPublication": False,
        })

    statuses = Counter(o["status"] for o in observations)
    matched_keys = {o["workKey"] for o in observations
                    if o["status"] == "research_quote"}
    return {
        "status": "technical_research_only",
        "checkedAtUtc": checked_at.astimezone(timezone.utc).isoformat(),
        "country": "MD", "currency": "MDL", "catalogVersion": catalog["catalogVersion"],
        "summary": {
            "workTypesMapped": len(reviewed),
            "workTypesInPilot": len(reviewed),
            "catalogLaborRates": len(LABOR_KEYS),
            "catalogWorkTypesWithResearchQuotes": len(matched_keys & set(LABOR_KEYS)),
            "catalogWorkTypesWithoutResearchQuotes": len(set(LABOR_KEYS) - matched_keys),
            "mappedSourceWorkPairs": len(observations),
            "distinctSourcePages": len(source_results),
            "pagesParsed": sum(r["status"] == "parsed" for r in source_results.values()),
            "quoteRowsExtracted": statuses["research_quote"],
            "quoteRowsRejectedByUnit": sum(
                o["reason"] == "unit_mismatch" for o in observations),
            "quotesWithScopeReviewRequired": sum(
                o["status"] == "research_quote" and
                o["scopeStatus"] == "review_required" for o in observations),
            "workTypesWithTwoBoundedAlignedSourcesForComparison": sum(
                r["comparisonCandidateOnly"] for r in reviewed),
            "publicationReadyLaborRates": 0,
        },
        "sourceHealth": [{"url": url, "host": validate_url(url), **result}
                         for url, result in sorted(source_results.items())],
        "observations": observations,
        "workReview": reviewed,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "automaticLaborPublicationEnabled": False,
        "note": ("Price row matches are research evidence only. Exact task scope, "
                 "layers, thickness, materials, page update date and tier policy "
                 "must all be reviewed before any proposed publication."),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--sources", type=Path, default=Path("labor_market_sources.json"))
    parser.add_argument("--rules", type=Path, default=Path("labor_live_match_rules.json"))
    parser.add_argument("--report", type=Path, default=Path("live_labor_quotes.json"))
    args = parser.parse_args(argv)
    try:
        report = collect(load(args.catalog), load(args.sources), load(args.rules),
                         datetime.now(timezone.utc))
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as err:
        print(f"LIVE LABOR RESEARCH FAILED: {err}", file=sys.stderr)
        return 1
    summary = report["summary"]
    print("=== COSTARO EXACT LABOR QUOTE RESEARCH ===")
    print(f"Work types covered: {summary['workTypesInPilot']}")
    print(f"Exact table labels and matching units found: {summary['quoteRowsExtracted']}")
    print(f"Quotes with scope review needed: {summary['quotesWithScopeReviewRequired']}")
    print(f"Comparison candidates (not approved): {summary['workTypesWithTwoBoundedAlignedSourcesForComparison']}")
    print("Published price changes: 0. App calculations unchanged.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
