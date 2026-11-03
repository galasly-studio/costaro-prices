#!/usr/bin/env python3
"""Research-only traceability audit for three material candidates.

Cross-checks configured retailers, collected observations, tier review and
manufacturer dossiers. It does NOT certify product quality or publish prices.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import median
from urllib.parse import urlparse

from validate_app_catalog import load


PINNED = {
    "glet_b62_satroc_8kg": ("finishPutty", "standard", 8),
    "glet_satroc_8kg": ("finishPutty", "premium", 8),
    "euroton_lav_7kg": ("interiorPaint", "standard", 7),
}

STRONG_METHODS = frozenset({
    "product_structured_sku",
    "product_microdata",
})


def index_rows(rows, label):
    if not isinstance(rows, list):
        raise ValueError("Missing rows: " + label)

    result = {}

    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Invalid row: " + label)

        key = row.get("id")

        if not isinstance(key, str) or not key or key in result:
            raise ValueError("Duplicate or invalid ID: " + label)

        result[key] = row

    return result


def valid_price(value):
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def is_fresh(value, now):
    try:
        observed = datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        if observed.tzinfo is None:
            return False

        elapsed = (
            now - observed.astimezone(timezone.utc)
        ).total_seconds()

        return -300 <= elapsed <= 86400
    except (AttributeError, TypeError, ValueError):
        return False


def audit(sources, observations, tiers, quality, *, now=None):
    now = now or datetime.now(timezone.utc)
    now = now.astimezone(timezone.utc)

    if (
        sources.get("country") != "MD"
        or sources.get("currency") != "MDL"
        or sources.get("automaticPublicationEnabled") is not False
        or observations.get("country") != "MD"
        or observations.get("currency") != "MDL"
    ):
        raise ValueError("Unsafe market or source configuration")

    if (
        tiers.get("status") != "human_review_only"
        or tiers.get("pricesChanged") is not False
        or tiers.get("automaticPublicationEnabled") is not False
        or tiers.get("approvedTierMappings") != 0
    ):
        raise ValueError("Tier research is not safely unapproved")

    if (
        quality.get("status") != "manufacturer_quality_research_only"
        or quality.get("publishedPricesChanged") is not False
        or quality.get("flutterCalculationsChanged") is not False
        or quality.get("tierMappingsChanged") is not False
    ):
        raise ValueError("Unsafe manufacturer quality report")

    source_rows = index_rows(sources.get("materials"), "sources")
    raw_rows = index_rows(observations.get("materials"), "observations")
    tier_rows = index_rows(tiers.get("products"), "tiers")
    quality_rows = index_rows(quality.get("products"), "quality")

    if set(quality_rows) != set(PINNED):
        raise ValueError("Unexpected manufacturer dossier product IDs")

    fresh = (
        tiers.get("observationsFresh") is True
        and is_fresh(observations.get("generatedAt"), now)
    )

    manufacturer_fresh = (
        quality.get("manufacturerEvidenceFresh") is True
        and is_fresh(quality.get("generatedAt"), now)
    )

    results = []

    for product_id, (material_key, tier_hint, weight) in PINNED.items():
        if (
            product_id not in source_rows
            or product_id not in raw_rows
            or product_id not in tier_rows
        ):
            raise ValueError("Missing research product: " + product_id)

        configured = source_rows[product_id]
        collected = raw_rows[product_id]
        tier = tier_rows[product_id]
        dossier = quality_rows[product_id]

        if (
            configured.get("catalogMaterialKey") != material_key
            or configured.get("tierCandidateForReview") != tier_hint
            or configured.get("priceTier") is not None
            or configured.get("packageWeightKg") != weight
            or configured.get("unit") != "bucket"
            or tier.get("catalogMaterialKey") != material_key
            or tier.get("tierHintForHumanReview") != tier_hint
            or dossier.get("catalogMaterialKey") != material_key
            or dossier.get("tierHintForHumanReview") != tier_hint
        ):
            raise ValueError("Material or package mismatch: " + product_id)

        if (
            dossier.get("qualityTierVerified") is not False
            or dossier.get("approvedForPublication") is not False
            or tier.get("tierQualityReviewed") is not False
            or tier.get("approvedForPublication") is not False
        ):
            raise ValueError("Unexpected approval: " + product_id)

        if (
            dossier.get("shopEvidence") != tier.get("sourceObservations")
            or dossier.get("researchPriceMedianMDL")
               != tier.get("candidateMedianMDL")
            or dossier.get("sourceResearchStatus") != tier.get("status")
        ):
            raise ValueError("Dossier provenance mismatch: " + product_id)

        shops = configured.get("sources")
        observed = collected.get("observations")

        if (
            not isinstance(shops, list)
            or len(shops) != 2
            or not isinstance(observed, list)
            or len(observed) != 2
        ):
            raise ValueError("Expected two retailer sources: " + product_id)

        hosts = set()
        methods = []
        prices = []
        all_candidates = True

        for shop, actual in zip(shops, observed):
            if not isinstance(shop, dict) or not isinstance(actual, dict):
                raise ValueError("Invalid retailer record")

            store = shop.get("store")
            url = shop.get("url")
            code = str(shop.get("productCode", "")).strip()

            if not isinstance(store, str) or not store or not code:
                raise ValueError("Missing retailer identity")

            parsed = urlparse(url if isinstance(url, str) else "")

            if (
                parsed.scheme != "https"
                or parsed.hostname not in (
                    "macons.md", "www.macons.md",
                    "obramag.md", "www.obramag.md",
                )
                or parsed.username
                or parsed.password
                or parsed.port
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Unapproved retailer URL")

            host = parsed.hostname.removeprefix("www.")

            if host in hosts:
                raise ValueError("Retail sources are not independent")

            hosts.add(host)

            if (
                actual.get("store") != store
                or actual.get("url") != url
                or str(actual.get("productCode", "")).strip() != code
            ):
                raise ValueError(
                    "Collected retailer identity mismatch: " + product_id
                )

            if (
                actual.get("status") != "candidate"
                or not valid_price(actual.get("price"))
            ):
                all_candidates = False
                continue

            methods.append(actual.get("extractionMethod"))
            prices.append(float(actual["price"]))

        source_evidence = tier.get("sourceObservations")

        if not isinstance(source_evidence, list):
            raise ValueError("Invalid tier source evidence")

        if tier.get("status") == "manual_review_candidate":
            if not all_candidates or len(source_evidence) != 2:
                raise ValueError(
                    "Tier candidate without two quotes: " + product_id
                )

            for actual, review in zip(observed, source_evidence):
                if (
                    review.get("store") != actual.get("store")
                    or review.get("url") != actual.get("url")
                    or str(review.get("productCode", "")).strip()
                       != str(actual.get("productCode", "")).strip()
                    or review.get("extractionMethod")
                       != actual.get("extractionMethod")
                    or not valid_price(review.get("priceMDL"))
                    or abs(
                        float(review["priceMDL"])
                        - float(actual["price"])
                    ) > 0.001
                ):
                    raise ValueError(
                        "Retail price provenance mismatch: " + product_id
                    )

            expected_median = round(median(prices), 2)

            if (
                not valid_price(tier.get("candidateMedianMDL"))
                or abs(
                    float(tier["candidateMedianMDL"]) - expected_median
                ) > 0.011
            ):
                raise ValueError("Retail median mismatch: " + product_id)

        elif tier.get("status") != "held":
            raise ValueError("Unexpected tier status: " + product_id)

        usable = (
            all_candidates
            and len(prices) == 2
            and len(source_evidence) == 2
            and tier.get("status") == "manual_review_candidate"
        )

        fully_structured = usable and all(
            method in STRONG_METHODS for method in methods
        )

        blockers = ["quality_tier_not_independently_verified"]

        if not fresh:
            blockers.append("retail_observations_stale")

        if not manufacturer_fresh:
            blockers.append("manufacturer_evidence_stale")

        if not usable:
            blockers.append("retail_evidence_incomplete")
        elif not fully_structured:
            blockers.append("visible_card_requires_manual_identity_review")

        if not usable:
            status = "held"
        elif fully_structured:
            status = "structured_sources_quality_review_pending"
        else:
            status = "mixed_sources_manual_identity_review"

        results.append({
            "id": product_id,
            "catalogMaterialKey": material_key,
            "tierHintOnly": tier_hint,
            "retailSourceCount": len(hosts),
            "candidateQuoteCount": len(prices),
            "methods": methods,
            "researchMedianMDL":
                tier.get("candidateMedianMDL") if usable else None,
            "retailObservationsFresh": fresh,
            "manufacturerEvidenceFresh": manufacturer_fresh,
            "fullyStructuredRetailMethods": bool(fully_structured),
            "sourceScreeningStatus": status,
            "blockers": blockers,
            "qualityTierVerified": False,
            "approvedForPublication": False,
        })

    return {
        "schemaVersion": 1,
        "status": "source_traceability_research_only",
        "generatedAt": now.isoformat(),
        "summary": {
            "productsReviewed": len(results),
            "twoCandidateQuotes": sum(
                row["candidateQuoteCount"] == 2
                for row in results
            ),
            "fullyStructuredDualRetailSources": sum(
                row["fullyStructuredRetailMethods"]
                for row in results
            ),
            "manualIdentityReviewRequired": sum(
                "visible_card_requires_manual_identity_review"
                in row["blockers"]
                for row in results
            ),
            "publicationApproved": 0,
        },
        "products": results,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
    }


def markdown(report):
    lines = [
        "# COSTARO — этап 30: происхождение магазинных данных",
        "",
        "**Исследовательский отчёт. Публикация цен запрещена.**",
        "",
        "| Материал | Исследовательская цена, MDL | Источники | Результат |",
        "|---|---:|---:|---|",
    ]

    for row in report["products"]:
        amount = row["researchMedianMDL"]
        shown = "—" if amount is None else f"{amount:.2f}"

        lines.append(
            f"| `{row['id']}` | {shown} | "
            f"{row['candidateQuoteCount']} | "
            f"{row['sourceScreeningStatus']} |"
        )

    lines.extend([
        "",
        "## Что означает результат",
        "",
        "- Структурированные данные и цена из видимой карточки "
        "имеют разный уровень доказательности.",
        "- Совпадение цен в двух магазинах не подтверждает качество.",
        "- Нельзя автоматически присваивать уровень "
        "budget/standard/premium.",
        "- Нельзя публиковать цены без отдельного разрешения.",
        "- Действующие цены, нормы и формулы COSTARO не изменены.",
        "",
        "## Причины, требующие проверки",
        "",
    ])

    for row in report["products"]:
        lines.append(f"### {row['id']}")
        for blocker in row["blockers"]:
            lines.append(f"- `{blocker}`")
        lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--sources", type=Path, default=Path("price_sources.json")
    )
    parser.add_argument(
        "--observations",
        type=Path,
        default=Path("price_observations.json"),
    )
    parser.add_argument(
        "--tiers",
        type=Path,
        default=Path("material_tier_review.json"),
    )
    parser.add_argument(
        "--quality",
        type=Path,
        default=Path("material_quality_dossiers.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("material_source_traceability.json"),
    )
    parser.add_argument(
        "--markdown",
        type=Path,
        default=Path("material_source_traceability_RU.md"),
    )

    args = parser.parse_args()

    paths = [
        args.sources.resolve(),
        args.observations.resolve(),
        args.tiers.resolve(),
        args.quality.resolve(),
        args.report.resolve(),
        args.markdown.resolve(),
    ]

    if len(set(paths)) != len(paths):
        raise ValueError("Input/output paths must be distinct")

    if args.report.exists() or args.markdown.exists():
        raise FileExistsError("Stage 30 report already exists")

    result = audit(
        load(args.sources),
        load(args.observations),
        load(args.tiers),
        load(args.quality),
    )

    args.report.write_text(
        json.dumps(
            result, ensure_ascii=False, indent=2, allow_nan=False
        ) + "\n",
        encoding="utf-8",
    )

    args.markdown.write_text(
        markdown(result),
        encoding="utf-8",
    )

    print("=== COSTARO STAGE 30 ===")
    print("Products:", result["summary"]["productsReviewed"])
    print(
        "Two-source candidates:",
        result["summary"]["twoCandidateQuotes"],
    )
    print(
        "Manual identity reviews:",
        result["summary"]["manualIdentityReviewRequired"],
    )
    print("Prices published: 0")


if __name__ == "__main__":
    main()