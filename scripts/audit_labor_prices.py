#!/usr/bin/env python3
"""Read-only audit of all 37 COSTARO labor rates and optional putty stage.

This validates numbers, schema, market evidence and tier order. It never
modifies prices.json, publishes prices or changes app calculations.
"""

from __future__ import annotations

import argparse
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path
import re
import sys
from urllib.parse import urlparse


LABOR_KEYS = (
    "removeWallpaperWork", "removePaintWork", "removeTileWork",
    "removeDecorativeWork", "plasterWork", "puttyWork", "primerWork",
    "wallpaperWork", "wallPaintWork", "wallTileWork", "decorativeWork",
    "floorRemoveSoftCoverWork", "floorRemoveTileWork", "floorRemoveOtherWork",
    "floorScreedWork", "selfLevelingFloorWork", "floorPrimerWork",
    "floorWaterproofingWork", "laminateWork", "vinylWork", "linoleumWork",
    "floorTileWork", "skirtingWork", "ceilingPaintWork", "ceilingPuttyWork",
    "ceilingPrimerWork", "drywallCeilingWork", "stretchCeilingTurnkey",
    "electricalDeviceInstallWork", "electricalSubboxInstallWork",
    "electricalSubboxHoleWork", "electricalCableLayWork",
    "electricalLightInstallWork", "electricalDeviceRemovalWork",
    "electricalLightRemovalWork", "plumbingWaterPipeWork",
    "plumbingSewerPipeWork",
)
LEVELS = ("budget", "standard", "premium")
assert len(LABOR_KEYS) == 37
LINEAR_KEYS = {
    "skirtingWork", "electricalCableLayWork",
    "plumbingWaterPipeWork", "plumbingSewerPipeWork",
}
PIECE_KEYS = {
    "electricalDeviceInstallWork", "electricalSubboxInstallWork",
    "electricalSubboxHoleWork", "electricalLightInstallWork",
    "electricalDeviceRemovalWork", "electricalLightRemovalWork",
}


def required_unit(key: str) -> str:
    return "m" if key in LINEAR_KEYS else "piece" if key in PIECE_KEYS else "m2"


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as stream:
        data = json.load(stream)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return data


def positive(value: object) -> bool:
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and value > 0)


def tier_errors(value: object, label: str) -> list[str]:
    if not isinstance(value, dict) or set(value) != set(LEVELS):
        return [f"{label}: exactly budget, standard and premium required"]
    if not all(positive(value[level]) for level in LEVELS):
        return [f"{label}: prices must be positive finite numbers"]
    if value["budget"] > value["standard"] or value["standard"] > value["premium"]:
        return [f"{label}: budget <= standard <= premium must hold"]
    return []


def catalog_errors(catalog: dict) -> list[str]:
    errors = []
    if catalog.get("schemaVersion") != 1:
        errors.append("schemaVersion must remain 1")
    if catalog.get("country") != "MD" or catalog.get("currency") != "MDL":
        errors.append("country/currency must be MD/MDL")
    version = catalog.get("catalogVersion")
    if not isinstance(version, str) or re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
        errors.append("catalogVersion must have major.minor.patch form")
    labor, material = catalog.get("laborPrices"), catalog.get("materialPrices")
    if not isinstance(labor, dict):
        errors.append("laborPrices must be an object")
    else:
        missing = sorted(set(LABOR_KEYS) - set(labor))
        unexpected = sorted(set(labor) - set(LABOR_KEYS))
        if missing:
            errors.append("Missing labor keys: " + ", ".join(missing))
        if unexpected:
            errors.append("Unexpected labor keys: " + ", ".join(unexpected))
        for key in LABOR_KEYS:
            if key in labor:
                errors.extend(tier_errors(labor[key], key))
    if not isinstance(material, dict) or len(material) != 41:
        errors.append("materialPrices must contain 41 entries")
    stage = catalog.get("laborStagePrices")
    if stage is not None:
        if not isinstance(stage, dict) or set(stage) != {"startPuttyWork"}:
            errors.append("laborStagePrices may contain only startPuttyWork")
        else:
            errors.extend(tier_errors(stage["startPuttyWork"], "startPuttyWork"))
    status = catalog.get("status")
    auto = catalog.get("automaticUpdatesEnabled")
    if not ((status == "draft" and auto is False) or
            (status == "published" and auto is True)):
        errors.append("Safety stop: incompatible publication status and automatic updates flag")
    return errors


def verify_observation(raw: object, key: str, today: date, age_limit: int) -> tuple[dict | None, str | None]:
    if not isinstance(raw, dict):
        return None, "observation_not_an_object"
    try:
        url = raw["url"]
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("HTTPS URL required")
        domain = parsed.hostname.lower().removeprefix("www.")
        checked = date.fromisoformat(raw["checkedOn"])
        if checked > today or (today - checked).days > age_limit:
            raise ValueError("source is too old or from the future")
        low, high = raw["min"], raw["max"]
        if not (positive(low) and positive(high) and low <= high):
            raise ValueError("min/max must be ordered positive numbers")
        if raw.get("scope") != key:
            raise ValueError("source scope does not match work type")
        if raw.get("unit") != required_unit(key):
            raise ValueError(f"unit must be {required_unit(key)} for {key}")
        return {"domain": domain, "min": low, "max": high, "url": url}, None
    except (KeyError, TypeError, ValueError) as err:
        return None, f"invalid_market_source: {err}"


def audit(catalog: dict, references: dict, today: date) -> dict:
    errors = catalog_errors(catalog)
    if errors:
        return {"ok": False, "errors": errors}
    source_map = references.get("sources")
    if not isinstance(source_map, dict):
        return {"ok": False, "errors": ["references.sources must be an object"]}
    unknown = sorted(set(source_map) - (set(LABOR_KEYS) | {"startPuttyWork"}))
    if unknown:
        return {"ok": False, "errors": ["Unknown reference keys: " + ", ".join(unknown)]}
    rows = []
    for key in LABOR_KEYS:
        prices = catalog["laborPrices"][key]
        observations = source_map.get(key, [])
        if not isinstance(observations, list):
            return {"ok": False, "errors": [f"{key}: sources must be an array"]}
        valid, warnings = [], []
        for raw in observations:
            item, error = verify_observation(raw, key, today, age_limit=180)
            if error:
                warnings.append(error)
            elif item:
                valid.append(item)
        independent = sorted({entry["domain"] for entry in valid})
        if len(independent) < 2:
            warnings.append("insufficient_independent_market_sources")
        else:
            observed_min = min(item["min"] for item in valid)
            observed_max = max(item["max"] for item in valid)
            if not observed_min * 0.8 <= prices["standard"] <= observed_max * 1.2:
                warnings.append("standard_price_outside_observed_range")
        if prices["premium"] / prices["budget"] > 4:
            warnings.append("wide_tier_spread_review")
        rows.append({
            "key": key,
            "prices": {level: prices[level] for level in LEVELS},
            "independentSources": len(independent),
            "sourceDomains": independent,
            "status": "COMPARISON READY" if not warnings else "NEEDS REVIEW",
            "warnings": warnings,
        })
    ready = sum(row["status"] == "COMPARISON READY" for row in rows)
    stage_rates = catalog.get("laborStagePrices", {}).get("startPuttyWork")
    stage_refs = source_map.get("startPuttyWork", [])
    if not isinstance(stage_refs, list):
        return {"ok": False, "errors": ["startPuttyWork: sources must be an array"]}
    stage_domains = set()
    for obs in stage_refs:
        item, error = verify_observation(obs, "startPuttyWork", today, age_limit=180)
        if item and not error:
            stage_domains.add(item["domain"])
    return {
        "ok": True,
        "auditDate": today.isoformat(),
        "catalogVersion": catalog["catalogVersion"],
        "catalogStatus": catalog["status"],
        "automaticUpdatesEnabled": catalog["automaticUpdatesEnabled"],
        "laborCount": len(rows),
        "materialCount": len(catalog["materialPrices"]),
        "readyCount": ready,
        "needsReviewCount": len(rows) - ready,
        "startPuttyWork": stage_rates,
        "startPuttyMarketSources": len(stage_domains),
        "startPuttyMarketStatus": (
            "NOT CONFIGURED" if stage_rates is None else
            "COMPARISON READY" if len(stage_domains) >= 2 else "NEEDS REVIEW"
        ),
        "rows": rows,
        "publishedPricesChanged": False,
    }


def summary_text(report: dict) -> str:
    if not report["ok"]:
        return "=== COSTARO LABOR AUDIT FAILED ===\n" + "\n".join(report["errors"]) + "\n"
    lines = [
        "=== COSTARO LABOR PRICE AUDIT ===",
        f"Labor rates: {report['laborCount']}",
        f"Material entries (count only): {report['materialCount']}",
        f"Market comparison ready: {report['readyCount']}",
        f"Need market review: {report['needsReviewCount']}",
        f"Start putty (extra tier): {report['startPuttyMarketStatus']}"
        f"; sources={report['startPuttyMarketSources']}",
        f"Catalog status: {report['catalogStatus']}", "",
    ]
    for row in report["rows"]:
        price = row["prices"]
        notes = ",".join(row["warnings"]) or "no automated warnings"
        lines.append(
            f"{row['key']} | {price['budget']}/{price['standard']}/{price['premium']}"
            f" | {row['status']} | sources={row['independentSources']} | {notes}"
        )
    lines.extend(["", "Published prices were NOT changed."])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument("--sources", type=Path, default=Path("labor_market_sources.json"))
    parser.add_argument("--report", type=Path, default=Path("labor_audit_report.json"))
    parser.add_argument("--summary", type=Path, default=Path("labor_audit_summary.txt"))
    parser.add_argument("--today", type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    args = parser.parse_args(argv)
    try:
        report = audit(load(args.catalog), load(args.sources), args.today)
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(f"AUDIT ERROR: {err}", file=sys.stderr)
        return 2
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    args.summary.write_text(summary_text(report), encoding="utf-8")
    print(summary_text(report), end="")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
