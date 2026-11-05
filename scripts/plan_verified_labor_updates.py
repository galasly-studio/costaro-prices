#!/usr/bin/env python3
"""Fail-closed planner for *manually verified* COSTARO labor quotes.

The automatically collected ``live_labor_quotes.json`` is research-only and
is NOT an eligible input: its priceDateVerified fields are false. An operator
must independently prepare an evidence document with two fixed-price,
technology-matched, dated offers and explicitly approve both source domains.
This module never writes an application catalog or publishes anything.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlparse

from validate_app_catalog import validate


TIERS = ("budget", "standard", "premium")
UNITS = ("m2", "m", "piece")
MAX_AGE = timedelta(hours=24)
MAX_FUTURE_DRIFT = timedelta(minutes=5)
MAX_PRICE_SPREAD = 0.12
MIN_CHANGE = 0.02
MAX_CHANGE = 0.08


def _date(value):
    if not isinstance(value, str):
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


def _domain(url):
    if not isinstance(url, str):
        return None
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    if (parsed.scheme != "https" or not host.endswith(".md")
            or parsed.username or parsed.password or parsed.port
            or not parsed.path.startswith("/")):
        return None
    return host


def _positive_price(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def _validate_policy(policy):
    if not isinstance(policy, dict) or policy.get("schemaVersion") != 1:
        raise ValueError("Invalid labor policy schema")
    if type(policy.get("enabled")) is not bool:
        raise ValueError("Labor policy enabled must be a JSON boolean")
    if type(policy.get("automaticPublicationApproved")) is not bool:
        raise ValueError("Labor publication consent must be a JSON boolean")
    approvals = policy.get("approvedMappings")
    if not isinstance(approvals, list):
        raise ValueError("approvedMappings must be a list")
    seen = set()
    for item in approvals:
        if not isinstance(item, dict):
            raise ValueError("Malformed labor mapping")
        if (not isinstance(item.get("workKey"), str)
                or item.get("tier") not in TIERS
                or item.get("unit") not in UNITS
                or not isinstance(item.get("scopeId"), str)
                or len(item["scopeId"].strip()) < 8
                or not isinstance(item.get("approvedSourceDomains"), list)
                or len(item["approvedSourceDomains"]) != 2
                or not all(isinstance(x, str) and x.endswith(".md")
                           for x in item["approvedSourceDomains"])
                or len(set(item["approvedSourceDomains"])) != 2
                or type(item.get("manuallyApproved")) is not bool):
            raise ValueError("Incomplete labor scope, unit, domains or approval")
        identity = (item["workKey"], item["tier"])
        if identity in seen:
            raise ValueError("Duplicate labor workKey/tier approval")
        seen.add(identity)


def plan(catalog, baseline, policy, evidence, *, now=None):
    """Return (decision, in-memory candidate); never update files."""
    _validate_policy(policy)
    if validate(catalog, baseline):
        raise ValueError("Labor planning requires a valid current catalog")
    if (not isinstance(evidence, dict) or evidence.get("schemaVersion") != 1
            or evidence.get("country") != "MD" or evidence.get("currency") != "MDL"
            or not isinstance(evidence.get("quotes"), list)):
        raise ValueError("Invalid curated labor evidence")

    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot_at = _date(evidence.get("generatedAt"))
    fresh = (snapshot_at is not None and
             now - MAX_AGE <= snapshot_at <= now + MAX_FUTURE_DRIFT)
    candidate = deepcopy(catalog)
    rows = []

    for mapping in policy["approvedMappings"]:
        key, tier = mapping["workKey"], mapping["tier"]
        group = "laborStagePrices" if key == "startPuttyWork" else "laborPrices"
        entry = catalog.get(group, {}).get(key)
        row = {"workKey": key, "tier": tier, "status": "held", "reason": None}
        quote_rows = [quote for quote in evidence["quotes"]
                      if isinstance(quote, dict) and quote.get("workKey") == key
                      and quote.get("tier") == tier]

        if not policy["enabled"] or not policy["automaticPublicationApproved"]:
            row["reason"] = "labor_publication_disabled_or_unapproved"
        elif mapping["manuallyApproved"] is not True:
            row["reason"] = "work_scope_not_manually_approved"
        elif entry is None:
            row["reason"] = "unknown_labor_work_key"
        elif not fresh:
            row["reason"] = "labor_evidence_not_fresh"
        elif len(quote_rows) != 2:
            row["reason"] = "two_exact_quotes_required"
        else:
            prices = []
            domains = set()
            for quote in quote_rows:
                domain = _domain(quote.get("url"))
                observed_at = _date(quote.get("verifiedAt"))
                if (quote.get("unit") != mapping["unit"]
                        or quote.get("scopeId") != mapping["scopeId"]
                        or quote.get("priceKind") != "fixed_price"
                        or quote.get("priceDateVerified") is not True
                        or quote.get("scopeVerified") is not True
                        or not _positive_price(quote.get("priceMDL"))
                        or domain is None
                        or domain not in mapping["approvedSourceDomains"]
                        or observed_at is None
                        or not now - MAX_AGE <= observed_at <= now + MAX_FUTURE_DRIFT):
                    row["reason"] = "unverified_scope_unit_date_or_source"
                    break
                domains.add(domain)
                prices.append(float(quote["priceMDL"]))

            if row["reason"] is None and len(domains) != 2:
                row["reason"] = "sources_not_independent"
            if row["reason"] is None and (
                    max(prices) - min(prices)) / min(prices) > MAX_PRICE_SPREAD:
                row["reason"] = "labor_price_spread_too_large"
            if row["reason"] is None:
                proposed = round(sum(prices) / 2, 2)
                previous = catalog[group][key][tier]
                original = baseline[group][key][tier]
                movement = (proposed - previous) / previous
                if abs(movement) < MIN_CHANGE:
                    row["reason"] = "labor_change_below_two_percent"
                elif abs(movement) > MAX_CHANGE:
                    row["reason"] = "labor_change_above_eight_percent"
                elif not original * 0.7 <= proposed <= original * 1.3:
                    row["reason"] = "outside_app_embedded_limit"
                else:
                    candidate[group][key][tier] = proposed
                    if validate(candidate, baseline):
                        candidate[group][key][tier] = previous
                        row["reason"] = "complete_catalog_validation_failed"
                    else:
                        row.update({"status": "proposed", "previousMDL": previous,
                                    "proposedMDL": proposed,
                                    "changePercent": round(movement * 100, 2)})
        rows.append(row)

    return ({"status": "read_only_proposals",
             "proposedCount": sum(item["status"] == "proposed" for item in rows),
             "approvedForPublication": False,
             "publishedPricesChanged": False,
             "laborUpdates": rows}, candidate)
