#!/usr/bin/env python3
"""Research-only, read-only availability check for Moldova labor-price pages.

An accessible page does NOT verify a saved labor price or authorize updates.
The catalog, observations and app formulas are never modified by this script.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone
import json
from pathlib import Path
import socket
import ssl
import sys
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

from audit_labor_prices import (
    LABOR_KEYS, audit, catalog_errors, load, verify_observation,
)


from labor_network_retry import open_with_guarded_retry

# Explicitly configured providers, not an open URL-fetching proxy.
ALLOWED_HOSTS = frozenset({
    "remont.md", "www.remont.md",
    "construct.md", "www.construct.md",
    "remontexpert.md", "www.remontexpert.md",
    "clickwork.md", "www.clickwork.md",
    "topmaster.md", "www.topmaster.md",
    "euroremontstyle.md", "www.euroremontstyle.md",
    "electricchisinau.md", "www.electricchisinau.md",
    "lumeamesterilor.md", "www.lumeamesterilor.md",
})
MAX_HTML_PREFIX = 32768
AGE_LIMIT_DAYS = 180


def validate_url(url: object) -> str:
    """Reject unapproved hosts, credentials, ports and unsafe redirects."""
    if not isinstance(url, str) or any(ord(ch) < 32 for ch in url):
        raise ValueError("invalid_source_url")
    parsed = urlparse(url)
    try:
        valid_port = parsed.port in (None, 443)
    except ValueError:
        valid_port = False
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username is not None or parsed.password is not None
            or not valid_port or not parsed.path.startswith("/")):
        raise ValueError("invalid_source_url")
    return parsed.hostname.removeprefix("www.")


class OnlyApprovedRedirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        try:
            validate_url(newurl)
        except ValueError as err:
            raise ValueError("unapproved_redirect") from err
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_html_prefix(url: str) -> str:
    """Download only a short HTML prefix; never extract or claim live rates."""
    validate_url(url)
    opener = urllib.request.build_opener(OnlyApprovedRedirects())
    request = urllib.request.Request(url, headers={
        "User-Agent": "COSTARO-LaborAvailabilityResearch/1.0",
        "Accept": "text/html",
    })
    with open_with_guarded_retry(opener, request, timeout=12) as response:
        validate_url(response.geturl())
        content_type = response.headers.get("Content-Type", "").lower()
        if "text/html" not in content_type:
            raise ValueError("unexpected_content_type")
        prefix = response.read(MAX_HTML_PREFIX)
        if not prefix.strip():
            raise ValueError("empty_response")
        return prefix.decode("utf-8", errors="replace")


def error_category(err: Exception) -> str:
    if isinstance(err, urllib.error.HTTPError):
        return f"http_{err.code}"
    if isinstance(err, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(err, urllib.error.URLError):
        if isinstance(err.reason, (TimeoutError, socket.timeout)):
            return "timeout"
        if isinstance(err.reason, socket.gaierror):
            return "dns_error"
        if isinstance(err.reason, ssl.SSLError):
            return "tls_error"
        return "network_error"
    if isinstance(err, ValueError):
        return str(err) if str(err) in {
            "invalid_source_url", "unapproved_redirect", "unexpected_content_type",
            "empty_response",
        } else "invalid_response"
    return "unexpected_error"


def looks_like_block_page(html: str) -> bool:
    """Only flag obvious blocks near the start; no extraction of quoted rates."""
    start = html[:5000].casefold()
    return any(marker in start for marker in (
        "cf-challenge", "cf-turnstile", "verify you are human",
        "just a moment...", "access denied", "captcha required",
    ))


def check_sources(catalog: dict, references: dict, today: date,
                  fetcher=fetch_html_prefix, pause=time.sleep) -> dict:
    """Fetch each valid page once, report staleness and gaps, fail closed."""
    errors = catalog_errors(catalog)
    if errors:
        raise ValueError("Invalid catalog: " + "; ".join(errors))
    source_map = references.get("sources")
    if not isinstance(source_map, dict):
        raise ValueError("references.sources must be an object")
    unknown = set(source_map) - (set(LABOR_KEYS) | {"startPuttyWork"})
    if unknown:
        raise ValueError("Unexpected source keys: " + ", ".join(sorted(unknown)))

    # Validate and deduplicate all configured sources before making requests.
    by_key = {}
    all_urls = set()
    for key in (*LABOR_KEYS, "startPuttyWork"):
        refs = source_map.get(key, [])
        if not isinstance(refs, list):
            raise ValueError(f"{key}: sources must be an array")
        current, stale, invalid = [], 0, 0
        for raw in refs:
            verified, reason = verify_observation(raw, key, today, AGE_LIMIT_DAYS)
            if reason:
                # Expired manual date cannot be refreshed by a successful HTTP fetch.
                if isinstance(raw, dict) and isinstance(raw.get("checkedOn"), str):
                    try:
                        when = date.fromisoformat(raw["checkedOn"])
                        is_stale = when > today or (today - when).days > AGE_LIMIT_DAYS
                    except ValueError:
                        is_stale = False
                    if is_stale:
                        stale += 1
                        continue
                invalid += 1
                continue
            try:
                domain = validate_url(verified["url"])
            except ValueError:
                invalid += 1
                continue
            current.append((verified["url"], domain))
            all_urls.add(verified["url"])
        by_key[key] = {"current": current, "stale": stale, "invalid": invalid,
                       "configured": len(refs)}

    results = {}
    host_refusals = {}
    last_host = None
    for url in sorted(all_urls):
        host = validate_url(url)
        if host in host_refusals:
            results[url] = {"status": "not_checked", "reason":
                            f"skipped_after_{host_refusals[host]}"}
            continue
        if last_host == host:
            pause(0.25)
        last_host = host
        try:
            html = fetcher(url)
            if not isinstance(html, str):
                raise ValueError("invalid_response")
            if looks_like_block_page(html):
                results[url] = {"status": "blocked", "reason": "challenge_page"}
            else:
                results[url] = {"status": "reachable", "reason":
                                "html_page_only_price_not_verified"}
        except (OSError, ValueError, UnicodeError) as err:
            reason = error_category(err)
            results[url] = {"status": "unavailable", "reason": reason}
            if reason in ("http_403", "http_429"):
                host_refusals[host] = reason

    rows = []
    for key in LABOR_KEYS:
        info = by_key[key]
        configured_domains = sorted({host for _, host in info["current"]})
        reachable_domains = sorted({host for url, host in info["current"]
                                    if results[url]["status"] == "reachable"})
        action = ("find_first_source" if not configured_domains else
                  "find_second_independent_source" if len(configured_domains) < 2 else
                  "verify_exact_live_work_rate_and_scope")
        rows.append({
            "key": key,
            "configuredReferences": info["configured"],
            "currentReferences": len(info["current"]),
            "staleReferences": info["stale"],
            "invalidReferences": info["invalid"],
            "currentIndependentDomains": len(configured_domains),
            "reachableIndependentDomains": len(reachable_domains),
            "nextAction": action,
            "livePriceVerified": False,
        })

    # Ensure structural consistency with the existing static labor audit.
    legacy_audit = audit(catalog, references, today)
    if not legacy_audit["ok"]:
        raise ValueError("Labor audit failed: " + "; ".join(legacy_audit["errors"]))
    return {
        "status": "research_only",
        "checkedOn": today.isoformat(),
        "market": "Moldova",
        "currency": "MDL",
        "summary": {
            "catalogLaborRates": len(LABOR_KEYS),
            "laborRatesWithNoCurrentReferences": sum(
                r["currentIndependentDomains"] == 0 for r in rows),
            "laborRatesWithOneCurrentIndependentDomain": sum(
                r["currentIndependentDomains"] == 1 for r in rows),
            "laborRatesWithAtLeastTwoCurrentIndependentDomains": sum(
                r["currentIndependentDomains"] >= 2 for r in rows),
            "uniqueUrlsConfiguredAndCurrent": len(results),
            "uniqueUrlsReachable": sum(r["status"] == "reachable" for r in results.values()),
            "uniqueUrlsBlockedOrUnavailable": sum(
                r["status"] in ("blocked", "unavailable") for r in results.values()),
            "uniqueUrlsSkipped": sum(r["status"] == "not_checked" for r in results.values()),
            "laborRatesLivePriceVerified": 0,
        },
        "sourceHealth": [{"url": url, "host": validate_url(url), **result}
                         for url, result in sorted(results.items())],
        "workRates": rows,
        "errorCategories": dict(sorted(Counter(
            r["reason"] for r in results.values() if r["status"] != "reachable"
        ).items())),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "automaticLaborPublicationEnabled": False,
        "note": "An accessible page does not verify prices, scope, dates or budget/standard/premium tiers.",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--sources", type=Path, default=Path("labor_market_sources.json"))
    parser.add_argument("--report", type=Path, default=Path("labor_source_health.json"))
    parser.add_argument("--today", type=date.fromisoformat,
                        default=datetime.now(timezone.utc).date())
    args = parser.parse_args(argv)
    try:
        report = check_sources(load(args.catalog), load(args.sources), args.today)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                               encoding="utf-8")
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(f"LABOR SOURCE CHECK FAILED: {err}", file=sys.stderr)
        return 1
    summary = report["summary"]
    print("=== COSTARO LABOR SOURCE HEALTH (RESEARCH ONLY) ===")
    print(f"Work rates: {summary['catalogLaborRates']}")
    print(f"Configured current pages: {summary['uniqueUrlsConfiguredAndCurrent']}")
    print(f"Reachable HTML pages: {summary['uniqueUrlsReachable']}")
    print(f"Live verified labor prices: {summary['laborRatesLivePriceVerified']}")
    print("Existing prices and formulas unchanged. Publication disabled.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
