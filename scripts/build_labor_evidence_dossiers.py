#!/usr/bin/env python3
"""Read-only evidence dossiers for all 38 COSTARO labor work types."""

from __future__ import annotations

import argparse
import copy
from collections import defaultdict
import json
from pathlib import Path
import sys

from audit_labor_prices import load
from build_labor_review_queue import build_queue


REVIEW_LABELS = {
    "no_exact_mapping": "Нет точной строки для технологии",
    "unit_conflict": "Неверная единица измерения у источника",
    "no_live_exact_quote": "Нет доступной точной строки",
    "scope_not_confirmed": "Не подтверждён состав работы",
    "insufficient_bounded_sources":
        "Недостаточно независимых сопоставимых источников",
    "preliminary_comparison_only": "Только предварительное сопоставление",
    "drift_outlier_manual_review":
        "Предварительное отклонение — ручная проверка",
}

ACTIONS = {
    "verify_specific_technology_before_mapping":
        "Определить технологию и отдельную расценку; "
        "не подставлять частную работу за общую.",
    "confirm_source_unit_without_conversion":
        "Проверить единицу в оригинальной строке; "
        "штуки нельзя переводить в погонные метры.",
    "check_exact_row_and_source_availability":
        "Проверить наличие точной строки и доступность сайта.",
    "verify_layers_thickness_and_included_operations":
        "Сверить слои, толщину, материалы и включённые операции.",
    "find_independent_scope_matched_dated_quote":
        "Найти второй независимый источник с тем же "
        "объёмом работ и датой тарифа.",
    "verify_individual_price_dates_and_tier_policy":
        "Вручную проверить дату каждой строки, "
        "технологию и политику ценового уровня.",
    "inspect_exact_scope_before_any_price_decision":
        "Проверить объём работ до любых решений по цене.",
}

UNITS = {
    "m": "пог. м",
    "m2": "м²",
    "piece": "шт.",
}


def build_dossiers(catalog, sources, rules, live, drift, leads, queue):
    """Regenerate the verified queue before accepting any evidence."""

    expected = build_queue(
        catalog, sources, rules, live, drift, leads
    )

    if queue != expected:
        raise ValueError(
            "Manual research queue differs from verified source reports"
        )

    grouped = defaultdict(list)

    for observation in live["observations"]:
        record = {
            "source": observation["source"],
            "url": observation["url"],
            "expectedLabel": observation["expectedLabel"],
            "unit": observation["expectedUnit"],
            "status": observation["status"],
            "reason": observation["reason"],
            "scopeStatus": observation["scopeStatus"],
            "scopeReason": observation["scopeReason"],
            "priceDateVerified": False,
            "approvedForPublication": False,
            "researchQuote": None,
        }

        if observation["status"] == "research_quote":
            kind = observation["priceKind"]

            amount = {
                "kind": kind,
                "minimumMDL": observation["minimumMDL"],
            }

            if kind == "lower_bound":
                if observation["maximumMDL"] is not None:
                    raise ValueError(
                        "Lower bound incorrectly supplied with upper limit"
                    )
            else:
                amount["maximumMDL"] = observation["maximumMDL"]

                if kind == "range_with_average":
                    amount["averageMDL"] = observation["averageMDL"]

            record["researchQuote"] = amount

        grouped[observation["workKey"]].append(record)

    dossiers = []

    for row in queue["workReview"]:
        group = row["reviewGroup"]
        action = row["nextManualAction"]
        key = row["workKey"]

        if (
            group not in REVIEW_LABELS
            or action not in ACTIONS
            or row["unit"] not in UNITS
        ):
            raise ValueError("Unknown review group, action, or unit")

        entries = grouped.pop(key, [])

        if len(entries) != row["configuredExactRows"]:
            raise ValueError(
                "Research evidence count differs from validated manual queue"
            )

        dossiers.append({
            "workKey": key,
            "unit": row["unit"],
            "priority": row["priority"],
            "reviewGroup": group,
            "reviewReasonRU": REVIEW_LABELS[group],
            "nextManualAction": action,
            "nextManualActionRU": ACTIONS[action],
            "exactResearchQuotes": row["exactResearchQuotes"],
            "rejectedUnitRows": row["rejectedUnitRows"],
            "manualLeads": copy.deepcopy(row["manualLeads"]),
            "evidenceRows": entries,
            "priceDateVerified": False,
            "approvedForPublication": False,
        })

    if grouped or len(dossiers) != queue["summary"]["workTypesReviewed"]:
        raise ValueError(
            "Unassigned research evidence or missing work"
        )

    return {
        "schemaVersion": 1,
        "status": "manual_evidence_review_only",
        "country": "MD",
        "currency": "MDL",
        "catalogVersion": catalog["catalogVersion"],
        "checkedAtUtc": live["checkedAtUtc"],
        "summary": {
            "workTypesReviewed": len(dossiers),
            "workTypesWithExactMappings":
                queue["summary"]["workTypesWithExactMappings"],
            "workTypesWithoutExactMappings":
                queue["summary"]["workTypesWithoutExactMappings"],
            "technologySpecificManualLeads":
                sum(len(d["manualLeads"]) for d in dossiers),
            "sourceObservations": len(live["observations"]),
            "exactResearchQuotes":
                sum(d["exactResearchQuotes"] for d in dossiers),
            "lowerBoundQuotes":
                sum(
                    x["researchQuote"] is not None
                    and x["researchQuote"]["kind"] == "lower_bound"
                    for d in dossiers
                    for x in d["evidenceRows"]
                ),
            "publicationReadyLaborRates": 0,
        },
        "dossiers": dossiers,
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "automaticLaborPublicationEnabled": False,
    }


def md(value):
    """Escape source-controlled strings in Markdown reports."""

    return (
        " ".join(str(value).split())
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("|", r"\|")
        .replace("`", "'")
    )


def quote_text(record):
    quote = record["researchQuote"]

    if quote is None:
        return (
            "нет подтверждённой строки ("
            + str(record["reason"])
            + ")"
        )

    kind = quote["kind"]
    unit = UNITS[record["unit"]]

    if kind == "lower_bound":
        return (
            "от "
            + str(quote["minimumMDL"])
            + " MDL/"
            + unit
        )

    if kind == "fixed_price":
        return str(quote["minimumMDL"]) + " MDL/" + unit

    if kind == "range_without_average":
        return (
            str(quote["minimumMDL"]) + "–"
            + str(quote["maximumMDL"])
            + " MDL/" + unit + " (без среднего)"
        )

    return (
        str(quote["minimumMDL"])
        + "–"
        + str(quote["maximumMDL"])
        + " MDL/"
        + unit
        + " (среднее "
        + str(quote["averageMDL"])
        + ")"
    )


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — досье проверки 38 расценок",
        "",
        "**Только исследование. Цены COSTARO и уровни "
        "бюджет/стандарт/премиум не изменяются.**",
        "",
        "Дата сбора наблюдений: "
        + md(report["checkedAtUtc"])
        + ". Это НЕ дата публикации тарифа.",
        "",
        "Работ: **{workTypesReviewed}**; "
        "точных настроенных соответствий: "
        "**{workTypesWithExactMappings}**; "
        "без соответствий: **{workTypesWithoutExactMappings}**; "
        "подсказок: **{technologySpecificManualLeads}**; "
        "строк-исследований: **{sourceObservations}**; "
        "строк «от»: **{lowerBoundQuotes}**.".format(**summary),
        "",
        "Подтверждено к публикации: **0**. "
        "Даже два сайта не доказывают актуальность, "
        "состав работы или применимость ценового уровня.",
        "",
        "| Приоритет | Работа | Причина проверки | Строк | Подсказок |",
        "|---:|---|---|---:|---:|",
    ]

    for dossier in report["dossiers"]:
        lines.append(
            f"| {dossier['priority']} | "
            f"`{md(dossier['workKey'])}` | "
            f"{md(dossier['reviewReasonRU'])} | "
            f"{len(dossier['evidenceRows'])} | "
            f"{len(dossier['manualLeads'])} |"
        )

    for dossier in report["dossiers"]:
        lines.extend([
            "",
            f"## Приоритет {dossier['priority']} — "
            f"`{md(dossier['workKey'])}`",
            f"- Единица: **{UNITS[dossier['unit']]}**.",
            f"- Причина: {md(dossier['reviewReasonRU'])}.",
            f"- Действие: {md(dossier['nextManualActionRU'])}.",
            "- Дата конкретной расценки не проверена; "
            "публикация запрещена.",
        ])

        if not dossier["evidenceRows"]:
            lines.append("- Точных настроенных строк нет.")

        for evidence in dossier["evidenceRows"]:
            price = quote_text(evidence)

            if evidence["scopeStatus"] == "review_required":
                scope = "условия требуют проверки"
            else:
                scope = "предварительное соответствие; не утверждено"

            lines.append(
                f"- Источник "
                f"[{md(evidence['source'])}]({evidence['url']}): "
                f"**{md(price)}**; "
                f"{md(scope)}; "
                f"строка «{md(evidence['expectedLabel'])}»."
            )

        for lead in dossier["manualLeads"]:
            lines.append(
                f"- Подсказка "
                f"[{md(lead['source'])}]({lead['url']}): "
                f"«{md(lead['label'])}»; "
                f"технология `{md(lead['technology'])}`; "
                f"ограничение `{md(lead['scopeLimitation'])}`. "
                "НЕ цена."
            )

    lines.extend([
        "",
        "## Ограничения",
        "",
        "Расценки «от» — только нижняя граница. "
        "Штуки не переводятся в метры.",
        "",
        "Для каждого тарифа отдельно проверяются дата, "
        "толщина, число слоёв, состав операций и технология.",
        "",
        "Никаких автоматических цен, публикации или назначения "
        "бюджет/стандарт/премиум.",
        "",
    ])

    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)

    parser.add_argument(
        "--catalog", type=Path, default=Path("prices.json")
    )
    parser.add_argument(
        "--sources", type=Path, default=Path("labor_market_sources.json")
    )
    parser.add_argument(
        "--rules", type=Path, default=Path("labor_live_match_rules.json")
    )
    parser.add_argument(
        "--quotes", type=Path, default=Path("live_labor_quotes.json")
    )
    parser.add_argument(
        "--drift", type=Path, default=Path("labor_drift_review.json")
    )
    parser.add_argument(
        "--leads", type=Path, default=Path("labor_manual_research_leads.json")
    )
    parser.add_argument(
        "--queue", type=Path, default=Path("labor_manual_review_queue.json")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("labor_evidence_dossiers.json")
    )
    parser.add_argument(
        "--markdown", type=Path,
        default=Path("labor_evidence_dossiers_RU.md")
    )

    args = parser.parse_args(argv)

    try:
        paths = (
            args.catalog,
            args.sources,
            args.rules,
            args.quotes,
            args.drift,
            args.leads,
            args.queue,
        )

        report = build_dossiers(*(load(path) for path in paths))

        args.report.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        args.markdown.write_text(
            render_markdown(report),
            encoding="utf-8",
        )

    except (OSError, ValueError, KeyError, TypeError) as error:
        print(
            f"LABOR EVIDENCE DOSSIERS FAILED: {error}",
            file=sys.stderr,
        )
        return 1

    print("=== COSTARO LABOR EVIDENCE DOSSIERS ===")
    print(f"Work types: {report['summary']['workTypesReviewed']}")
    print(f"Source observations: {report['summary']['sourceObservations']}")
    print(f"Unmapped work types: {report['summary']['workTypesWithoutExactMappings']}")
    print("Published or approved prices: 0")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())