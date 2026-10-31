#!/usr/bin/env python3
"""Check a full COSTARO catalog against the app's immutable price baseline.

This mirrors the safety rules in lib/data/moldova_prices.dart and
lib/services/remote_price_catalog_service.dart (2026-11-01 snapshot).
It never updates or publishes prices.
"""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import sys


LEVELS = ("budget", "standard", "premium")
VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")


def reject_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"Duplicate JSON key: {key}")
        result[key] = value
    return result


def reject_constant(value):
    raise ValueError(f"Non-finite JSON value: {value}")


def load(path: Path) -> dict:
    with path.open("r", encoding="utf-8-sig") as stream:
        value = json.load(
            stream,
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    if not isinstance(value, dict):
        raise ValueError(f"{path}: top-level JSON must be an object")
    return value


def positive_number(value) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def version_valid(value) -> bool:
    return (
        isinstance(value, str)
        and VERSION.fullmatch(value) is not None
        and all(int(part) <= 999999 for part in value.split("."))
    )


def check_price(value, baseline, label: str, errors: list[str]) -> None:
    if not positive_number(value):
        errors.append(f"{label}: price must be a finite positive number")
    elif not positive_number(baseline):
        errors.append(f"{label}: invalid embedded baseline")
    elif value < baseline * 0.7 - 1e-9 or value > baseline * 1.3 + 1e-9:
        errors.append(f"{label}: more than 30% away from app baseline")


def check_tiers(value, baseline, label: str, pack: bool, errors: list[str]) -> None:
    if not isinstance(value, dict) or set(value) != set(LEVELS):
        errors.append(f"{label}: exactly three price levels required")
        return
    if not isinstance(baseline, dict) or set(baseline) != set(LEVELS):
        errors.append(f"{label}: invalid embedded baseline levels")
        return

    prices = []
    for level in LEVELS:
        current, reference = value[level], baseline[level]
        path = f"{label}.{level}"
        if pack:
            if not isinstance(current, dict) or not isinstance(reference, dict):
                errors.append(f"{path}: expected material package")
                return
            if set(current) != {"name", "unit", "amount", "price"}:
                errors.append(f"{path}: package fields changed")
                return
            for invariant in ("name", "unit", "amount"):
                unchanged = current.get(invariant) == reference.get(invariant)
                if invariant == "amount" and not positive_number(current.get(invariant)):
                    unchanged = False
                if not unchanged:
                    errors.append(f"{path}: forbidden change of {invariant}")
            current, reference = current["price"], reference["price"]
        check_price(current, reference, path, errors)
        prices.append(current)

    if all(positive_number(p) for p in prices):
        if not (prices[0] <= prices[1] <= prices[2]):
            errors.append(f"{label}: budget <= standard <= premium is required")


def validate(catalog: dict, baseline: dict) -> list[str]:
    """Return all detectable errors without mutating either input."""
    errors: list[str] = []
    if type(catalog.get("schemaVersion")) is not int or catalog.get("schemaVersion") != 1:
        errors.append("schemaVersion must be 1")
    if catalog.get("country") != "MD" or catalog.get("currency") != "MDL":
        errors.append("country and currency must be MD/MDL")
    if not version_valid(catalog.get("catalogVersion")):
        errors.append("Invalid catalogVersion")

    status, enabled = catalog.get("status"), catalog.get("automaticUpdatesEnabled")
    if not ((status == "draft" and enabled is False) or
            (status == "published" and enabled is True)):
        errors.append("status/automaticUpdatesEnabled combination is invalid")

    for group_name, expected_count in (("laborPrices", 37), ("materialPrices", 41)):
        entries = catalog.get(group_name)
        references = baseline.get(group_name)
        if not isinstance(entries, dict) or not isinstance(references, dict):
            errors.append(f"{group_name} must be a JSON object")
            continue
        if len(references) != expected_count:
            errors.append(f"{group_name}: invalid frozen baseline count")
            continue
        if set(entries) != set(references):
            errors.append(f"{group_name}: missing or unknown catalog keys")
            continue
        for key, original in references.items():
            is_pack = isinstance(original, dict) and isinstance(original.get("budget"), dict)
            check_tiers(entries[key], original, f"{group_name}.{key}", is_pack, errors)

    # The 38th labor rate is a compatible optional top-level extension.
    # Once approved and deployed, it must not silently disappear.
    stage = catalog.get("laborStagePrices")
    stage_baseline = baseline.get("laborStagePrices")
    if stage_baseline is not None:
        if not isinstance(stage, dict) or set(stage) != {"startPuttyWork"}:
            errors.append("laborStagePrices.startPuttyWork must be preserved")
        else:
            check_tiers(
                stage["startPuttyWork"],
                stage_baseline["startPuttyWork"],
                "laborStagePrices.startPuttyWork",
                False,
                errors,
            )
    elif stage is not None:
        errors.append("Unexpected laborStagePrices extension")

    return errors


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=Path("prices.json"))
    parser.add_argument(
        "--baseline", type=Path, default=Path("app_embedded_baseline.json")
    )
    arguments = parser.parse_args(argv)
    try:
        errors = validate(load(arguments.catalog), load(arguments.baseline))
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"CATALOG INPUT ERROR: {error}", file=sys.stderr)
        return 2
    if errors:
        for error in errors:
            print(f"CATALOG REJECTED: {error}", file=sys.stderr)
        return 1
    print("COSTARO catalog matches application schema and embedded safety limits")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
