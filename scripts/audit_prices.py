import json
import statistics
from datetime import datetime, timezone
from pathlib import Path


CATALOG_FILE = Path("prices.json")
SOURCES_FILE = Path("price_sources.json")
OBSERVATIONS_FILE = Path("price_observations.json")
REPORT_FILE = Path("price_audit_report.json")

MIN_INDEPENDENT_STORES = 2
MAX_PRICE_SPREAD = 0.20


def load_json(path):
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def main():
    catalog = load_json(CATALOG_FILE)
    sources = load_json(SOURCES_FILE)
    observations = load_json(OBSERVATIONS_FILE)

    material_prices = catalog["materialPrices"]
    labor_prices = catalog["laborPrices"]

    catalog_keys = set(material_prices.keys())

    source_materials = sources.get("materials", [])
    observation_materials = observations.get("materials", [])

    observations_by_id = {
        item["id"]: item
        for item in observation_materials
    }

    report_materials = []
    covered_catalog_keys = set()

    total_sources = 0
    successful_sources = 0
    unavailable_sources = 0

    for material in source_materials:
        material_id = material["id"]
        catalog_key = material.get("catalogMaterialKey")

        configured_sources = material.get("sources", [])
        total_sources += len(configured_sources)

        # Считаем материал охваченным мониторингом,
        # только если для него настроен хотя бы один источник.
        if catalog_key in catalog_keys and configured_sources:
            covered_catalog_keys.add(catalog_key)

        observation = observations_by_id.get(material_id, {})
        results = observation.get("observations", [])

        candidates = []

        for result in results:
            price = result.get("price")
            status = result.get("status")

            if (
                status == "candidate"
                and isinstance(price, (int, float))
                and not isinstance(price, bool)
                and price > 0
            ):
                successful_sources += 1
                candidates.append(result)
            else:
                unavailable_sources += 1

        unique_stores = {
            str(result.get("store", "")).strip().lower()
            for result in candidates
            if result.get("store")
        }

        prices = [
            float(result["price"])
            for result in candidates
        ]

        median_price = (
            statistics.median(prices)
            if prices
            else None
        )

        spread = None

        if len(prices) >= 2 and min(prices) > 0:
            spread = (
                max(prices) - min(prices)
            ) / min(prices)

        problems = []

        if catalog_key not in catalog_keys:
            problems.append("unknown_catalog_key")

        if not configured_sources:
            problems.append("no_sources")

        if len(unique_stores) < MIN_INDEPENDENT_STORES:
            problems.append("insufficient_stores")

        if spread is not None and spread > MAX_PRICE_SPREAD:
            problems.append("price_spread_too_high")

        if len(results) < len(configured_sources):
            problems.append("missing_observations")

        if len(results) > len(configured_sources):
            problems.append("unexpected_observations")

        if any(
            result.get("status") != "candidate"
            for result in results
        ):
            problems.append("unavailable_source")

        comparison_ready = (
            catalog_key in catalog_keys
            and len(unique_stores) >= MIN_INDEPENDENT_STORES
            and spread is not None
            and spread <= MAX_PRICE_SPREAD
            and len(results) == len(configured_sources)
        )

        report_materials.append({
            "id": material_id,
            "catalogMaterialKey": catalog_key,
            "configuredSources": len(configured_sources),
            "successfulCandidates": len(candidates),
            "independentStoreNames": sorted(unique_stores),
            "candidateMedianMDL": median_price,
            "relativePriceSpread": spread,
            "comparisonReady": comparison_ready,
            "verifiedForPublication": False,
            "problems": problems,
        })

    uncovered_keys = sorted(
        catalog_keys - covered_catalog_keys
    )

    comparison_ready_count = sum(
        1
        for material in report_materials
        if material["comparisonReady"]
    )

    report = {
        "generatedAt": datetime.now(
            timezone.utc
        ).isoformat(),
        "country": "MD",
        "currency": "MDL",
        "status": "audit_only",
        "automaticPublicationEnabled": False,
        "summary": {
            "catalogMaterials": len(catalog_keys),
            "catalogLaborRates": len(labor_prices),
            "materialsWithMonitoring": len(
                covered_catalog_keys
            ),
            "materialsWithoutMonitoring": len(
                uncovered_keys
            ),
            "configuredSources": total_sources,
            "successfulCandidates": successful_sources,
            "unavailableOrInvalidObservations": (
                unavailable_sources
            ),
            "materialsReadyForComparison": (
                comparison_ready_count
            ),
            "verifiedForPublication": 0,
        },
        "uncoveredMaterialKeys": uncovered_keys,
        "materials": report_materials,
        "laborAuditStatus": "not_started",
        "publishedPricesChanged": False,
    }

    REPORT_FILE.write_text(
        json.dumps(
            report,
            ensure_ascii=False,
            indent=2,
        ) + "\n",
        encoding="utf-8",
    )

    summary = report["summary"]

    print("=== COSTARO PRICE AUDIT ===")
    print(
        "Materials in catalog:",
        summary["catalogMaterials"],
    )
    print(
        "Labor rates in catalog:",
        summary["catalogLaborRates"],
    )
    print(
        "Materials monitored:",
        summary["materialsWithMonitoring"],
    )
    print(
        "Materials not monitored:",
        summary["materialsWithoutMonitoring"],
    )
    print(
        "Configured sources:",
        summary["configuredSources"],
    )
    print(
        "Successful candidates:",
        summary["successfulCandidates"],
    )
    print(
        "Materials ready for comparison:",
        summary["materialsReadyForComparison"],
    )

    print("\n=== MATERIAL STATUS ===")

    for material in report_materials:
        print(
            material["catalogMaterialKey"],
            "|",
            "COMPARISON READY"
            if material["comparisonReady"]
            else "NEEDS REVIEW",
            "|",
            ",".join(material["problems"])
            or "no automated warnings",
        )

    print("\nReport saved:", REPORT_FILE)
    print("Published prices were NOT changed.")


if __name__ == "__main__":
    main()
