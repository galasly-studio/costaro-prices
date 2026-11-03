#!/usr/bin/env python3
"""Read-only batch research of priority manufacturer sources.

This module does not edit prices, estimates, formulas, technical norms,
quality tiers, publication decisions, or the Flutter application.
Network reachability is NEVER treated as verified technical evidence.
"""

from __future__ import annotations

import json
import os
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import (
    HTTPRedirectHandler,
    Request,
    build_opener,
)

FAMILY_FILE = "material_family_criteria.json"
PRIORITY_FILE = "priority_material_criteria.json"
LEADS_FILE = "manufacturer_evidence_leads.json"
QUEUE_FILE = "manufacturer_review_queue.json"

REPORT_FILE = "priority_source_batch_review.json"
MARKDOWN_FILE = "priority_source_batch_review_RU.md"

SOURCE_FORMATS = {
    "baumit.ro": "pdf",
    "knauf.com": "pdf",
    "www.egger.com": "pdf",
    "storage.mtender.gov.md": "pdf",
    "latrivenetacavi.nexans.com": "html",
    "supraten.md": "html",
}

MAX_CONCURRENT_HOSTS = 4
NETWORK_TIMEOUT_SECONDS = 9
MAX_SAMPLE_BYTES = 2048

BLOCKING_HTTP_CODES = {403, 429}


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def check_source_url(url):
    if not isinstance(url, str):
        raise ValueError("Manufacturer source URL must be a string")

    parsed = urlsplit(url)

    if (
        parsed.scheme != "https"
        or parsed.hostname not in SOURCE_FORMATS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
    ):
        raise ValueError(
            "Manufacturer source is outside the approved HTTPS hosts"
        )

    return parsed.hostname


class SameHostRedirect(HTTPRedirectHandler):
    """Reject redirects to another host or to unencrypted HTTP."""

    def redirect_request(
        self, request, response, code, message, headers, new_url
    ):
        old = urlsplit(request.full_url)
        new = urlsplit(new_url)

        if new.scheme != "https" or new.hostname != old.hostname:
            raise URLError("cross-host or insecure redirect rejected")

        return super().redirect_request(
            request, response, code, message, headers, new_url
        )


def fetch_source(url):
    """One bounded request; no retry, no credentials, no scraping bypass."""

    check_source_url(url)

    request = Request(
        url,
        headers={
            "User-Agent": "COSTARO-ReadOnly-ResearchAudit/1.0",
            "Accept": "application/pdf,text/html;q=0.9,*/*;q=0.5",
        },
    )

    opener = build_opener(SameHostRedirect())

    try:
        with opener.open(
            request,
            timeout=NETWORK_TIMEOUT_SECONDS,
        ) as response:
            sample = response.read(MAX_SAMPLE_BYTES)

            stripped = sample.lstrip().lower()

            return {
                "httpStatus": response.status,
                "contentType": response.headers.get_content_type(),
                "finalUrl": response.geturl(),
                "pdfSignature": sample.lstrip().startswith(b"%PDF-"),
                "htmlSignature": (
                    b"<html" in stripped
                    or b"<!doctype html" in stripped
                ),
                "networkError": None,
            }

    except HTTPError as error:
        return {
            "httpStatus": error.code,
            "contentType": None,
            "finalUrl": url,
            "pdfSignature": False,
            "htmlSignature": False,
            "networkError": None,
        }

    except (URLError, TimeoutError, OSError, ValueError) as error:
        return {
            "httpStatus": None,
            "contentType": None,
            "finalUrl": url,
            "pdfSignature": False,
            "htmlSignature": False,
            "networkError": str(error)[:180],
        }


def classify_source(url, observation):
    if observation.get("networkError"):
        return "unreachable_or_redirect_rejected"

    code = observation.get("httpStatus")

    if code in BLOCKING_HTTP_CODES:
        return "blocked_or_throttled"

    if not isinstance(code, int) or not 200 <= code < 300:
        return "http_error"

    original_host = urlsplit(url).hostname
    final_host = urlsplit(observation.get("finalUrl") or "").hostname

    if final_host != original_host:
        return "redirect_host_mismatch"

    expected = SOURCE_FORMATS[original_host]

    if expected == "pdf":
        return (
            "reachable_format_only"
            if observation.get("pdfSignature")
            else "document_format_mismatch"
        )

    content_type = observation.get("contentType")

    if (
        content_type in ("text/html", "application/xhtml+xml")
        or observation.get("htmlSignature")
    ):
        return "reachable_format_only"

    return "document_format_mismatch"


def scan_one_host(items, fetcher):
    """Serial requests per host permit a 403/429 circuit breaker."""

    results = []
    blocked = False

    for item in items:
        url = item["sourceUrl"]

        if blocked:
            results.append(
                (
                    item["catalogMaterialKey"],
                    {
                        "sourceStatus": "skipped_after_host_block",
                        "httpStatus": None,
                        "contentType": None,
                        "finalUrl": None,
                        "networkError": None,
                    },
                )
            )
            continue

        try:
            observation = fetcher(url)
            status = classify_source(url, observation)
        except Exception as error:
            observation = {
                "httpStatus": None,
                "contentType": None,
                "finalUrl": None,
                "networkError": str(error)[:180],
            }
            status = "unreachable_or_redirect_rejected"

        results.append(
            (
                item["catalogMaterialKey"],
                {
                    "sourceStatus": status,
                    "httpStatus": observation.get("httpStatus"),
                    "contentType": observation.get("contentType"),
                    "finalUrl": observation.get("finalUrl"),
                    "networkError": observation.get("networkError"),
                },
            )
        )

        if observation.get("httpStatus") in BLOCKING_HTTP_CODES:
            blocked = True

    return results


def validate_evidence_inputs(family, priority, leads, queue):
    families = family["families"]
    priority_items = priority["materials"]
    lead_items = leads["candidates"]

    catalog_keys = [
        key
        for group in families
        for key in group["catalogMaterialKeys"]
    ]

    if (
        len(catalog_keys) != len(set(catalog_keys))
        or len(catalog_keys) != family["summary"]["catalogMaterials"]
    ):
        raise ValueError("Material family coverage is incomplete or duplicated")

    priority_keys = [x["catalogMaterialKey"] for x in priority_items]
    lead_keys = [x["catalogMaterialKey"] for x in lead_items]

    if (
        len(priority_keys) != len(set(priority_keys))
        or len(lead_keys) != len(set(lead_keys))
        or set(priority_keys) != set(lead_keys)
        or not set(priority_keys).issubset(set(catalog_keys))
    ):
        raise ValueError("Priority products and manufacturer leads disagree")

    for material in priority_items:
        checks = material["technicalChecks"]

        criterion_ids = [x["criterionId"] for x in checks]

        if not criterion_ids or len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("Missing or duplicated technical criteria")

        if material.get("approvedForPublication"):
            raise ValueError("Unexpected publication approval in research input")

        if material.get("qualityTierApproved"):
            raise ValueError("Unexpected automatic quality-tier approval")

        for criterion in checks:
            if (
                criterion.get("evidenceProvided")
                or criterion.get("evidenceReviewed")
                or criterion.get("verifiedValue") is not None
            ):
                raise ValueError(
                    "Newly verified evidence requires a separate review process"
                )

    priority_by_key = {
        item["catalogMaterialKey"]: item
        for item in priority_items
    }

    for lead in lead_items:
        check_source_url(lead["sourceUrl"])

        allowed_criteria = {
            x["criterionId"]
            for x in priority_by_key[
                lead["catalogMaterialKey"]
            ]["technicalChecks"]
        }

        recorded = [x["criterionId"] for x in lead["sourceClaims"]]

        if (
            len(recorded) != len(set(recorded))
            or not set(recorded).issubset(allowed_criteria)
        ):
            raise ValueError("Manufacturer statements do not match criteria")

        if lead.get("approvedForPublication") or lead.get(
            "qualityTierApproved"
        ):
            raise ValueError("Unreviewed manufacturer claim was approved")

        for claim in lead["sourceClaims"]:
            if (
                claim.get("independentlyVerified")
                or claim.get("approvedAsQualityEvidence")
            ):
                raise ValueError(
                    "Independently verified claims need separate authorization"
                )

    if not isinstance(queue.get("tasks"), list):
        raise ValueError("Manufacturer research queue is missing")

    return catalog_keys


def build_report(family, priority, leads, queue, fetcher=fetch_source):
    catalog_keys = validate_evidence_inputs(
        family, priority, leads, queue
    )

    priority_by_key = {
        item["catalogMaterialKey"]: item
        for item in priority["materials"]
    }

    leads_by_key = {
        item["catalogMaterialKey"]: item
        for item in leads["candidates"]
    }

    grouped_sources = defaultdict(list)

    for lead in leads["candidates"]:
        host = check_source_url(lead["sourceUrl"])
        grouped_sources[host].append(lead)

    with ThreadPoolExecutor(
        max_workers=MAX_CONCURRENT_HOSTS
    ) as executor:
        host_results = list(
            executor.map(
                lambda items: scan_one_host(items, fetcher),
                grouped_sources.values(),
            )
        )

    observations = {
        key: result
        for host_batch in host_results
        for key, result in host_batch
    }

    materials = []

    for key in sorted(priority_by_key):
        profile = priority_by_key[key]
        lead = leads_by_key[key]

        checks = profile["technicalChecks"]

        recorded = {
            claim["criterionId"]
            for claim in lead["sourceClaims"]
        }

        missing = [
            check["criterionId"]
            for check in checks
            if check["criterionId"] not in recorded
        ]

        materials.append(
            {
                "catalogMaterialKey": key,
                "materialNameRu": profile["materialNameRu"],
                "technicalFamilyId": profile["technicalFamilyId"],
                "researchProductRu": lead["researchProductRu"],
                "sourceUrl": lead["sourceUrl"],
                "sourceHost": check_source_url(lead["sourceUrl"]),
                "sourceSpecificity": lead["sourceSpecificity"],
                "expectedDocumentFormat": SOURCE_FORMATS[
                    check_source_url(lead["sourceUrl"])
                ],
                **observations[key],
                "technicalCriteriaTotal": len(checks),
                "manufacturerStatementsRecorded": len(recorded),
                "missingCriterionIds": missing,
                "independentlyVerifiedCriteria": 0,
                "exactSkuIdentityApproved": False,
                "qualityTierApproved": False,
                "approvedForPublication": False,
            }
        )

    family_matrix = []

    for group in family["families"]:
        keys = group["catalogMaterialKeys"]

        family_matrix.append(
            {
                "familyId": group["familyId"],
                "titleRu": group["titleRu"],
                "catalogMaterialCount": len(keys),
                "catalogMaterialKeys": keys,
                "priorityMaterialKeys": [
                    key for key in keys if key in priority_by_key
                ],
                "familyCriteriaDoNotApproveIndividualProducts": True,
            }
        )

    criteria_total = sum(
        x["technicalCriteriaTotal"] for x in materials
    )

    manufacturer_statements = sum(
        x["manufacturerStatementsRecorded"] for x in materials
    )

    summary = {
        "catalogMaterialsCovered": len(catalog_keys),
        "technicalFamiliesCovered": len(family_matrix),
        "priorityMaterialsAudited": len(materials),
        "uniqueManufacturerHosts": len(grouped_sources),
        "sourceRequestsAttempted": sum(
            item["sourceStatus"] != "skipped_after_host_block"
            for item in materials
        ),
        "sourcesWithReachableFormatOnly": sum(
            item["sourceStatus"] == "reachable_format_only"
            for item in materials
        ),
        "blockedOrThrottledSources": sum(
            item["sourceStatus"] == "blocked_or_throttled"
            for item in materials
        ),
        "sourceFormatMismatches": sum(
            item["sourceStatus"] == "document_format_mismatch"
            for item in materials
        ),
        "technicalCriteriaTotal": criteria_total,
        "manufacturerStatementsRecorded": manufacturer_statements,
        "criteriaMissingManufacturerStatement": (
            criteria_total - manufacturer_statements
        ),
        "independentlyVerifiedCriteria": 0,
        "manualResearchTasks": len(queue["tasks"]),
        "qualityTiersApproved": 0,
        "approvedForPublication": 0,
    }

    if manufacturer_statements > criteria_total:
        raise ValueError("More claims than technical criteria")

    return {
        "schemaVersion": 1,
        "status": "read_only_bulk_manufacturer_source_research",
        "checkedAtUtc": datetime.now(timezone.utc).isoformat(),
        "principle": (
            "Transport and document format do not verify exact SKU, "
            "technical properties, price, retail stock, or quality tier."
        ),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "tierMappingsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "summary": summary,
        "families": family_matrix,
        "priorityMaterials": materials,
    }


def markdown_escape(value):
    return str(value).replace("|", "\\|").replace("\n", " ")


def make_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — пакетная проверка технических источников",
        "",
        "Это исследование, а не подтверждение качества или цены.",
        "",
        f"- Материалов каталога: **{summary['catalogMaterialsCovered']}**.",
        f"- Технических семейств: **{summary['technicalFamiliesCovered']}**.",
        f"- Приоритетных материалов: **{summary['priorityMaterialsAudited']}**.",
        f"- Проверенных обращений к источникам: **{summary['sourceRequestsAttempted']}**.",
        f"- Доступный формат документа/страницы: **{summary['sourcesWithReachableFormatOnly']}**.",
        f"- Блокировка HTTP 403/429: **{summary['blockedOrThrottledSources']}**.",
        f"- Несовпадение формата документа: **{summary['sourceFormatMismatches']}**.",
        f"- Технических критериев: **{summary['technicalCriteriaTotal']}**.",
        f"- Заявлений производителя: **{summary['manufacturerStatementsRecorded']}**.",
        f"- Недостающих заявлений: **{summary['criteriaMissingManufacturerStatement']}**.",
        f"- Задач ручной проверки: **{summary['manualResearchTasks']}**.",
        "- Независимо подтверждённых технических критериев: **0**.",
        "- Утверждённых категорий качества: **0**.",
        "- Разрешённых к публикации изменений: **0**.",
        "",
        "## Восемь приоритетных материалов",
        "",
        "| Материал | Источник | Доступность | Заявления / критерии | Пробелы |",
        "|---|---|---|---:|---|",
    ]

    for item in report["priorityMaterials"]:
        missing = ", ".join(item["missingCriterionIds"]) or "—"

        lines.append(
            "| "
            + markdown_escape(item["materialNameRu"])
            + " | "
            + markdown_escape(item["sourceHost"])
            + " | "
            + markdown_escape(item["sourceStatus"])
            + " | "
            + str(item["manufacturerStatementsRecorded"])
            + " / "
            + str(item["technicalCriteriaTotal"])
            + " | "
            + markdown_escape(missing)
            + " |"
        )

    lines += [
        "",
        "## Охват всего каталога по техническим семействам",
        "",
        "| Семейство | Материалов | Приоритетных |",
        "|---|---:|---:|",
    ]

    for group in report["families"]:
        lines.append(
            "| "
            + markdown_escape(group["titleRu"])
            + " | "
            + str(group["catalogMaterialCount"])
            + " | "
            + str(len(group["priorityMaterialKeys"]))
            + " |"
        )

    lines += [
        "",
        "## Правила интерпретации",
        "",
        "- `reachable_format_only` — сайт отдал страницу или PDF нужного формата. Содержание ещё не проверено.",
        "- `document_format_mismatch` — вместо ожидаемого формата получено что-то другое; нужна ручная проверка.",
        "- `blocked_or_throttled` — источник ограничил доступ; повторных обращений к этому хосту в запуске нет.",
        "- `skipped_after_host_block` — дальнейшие запросы к заблокировавшему хосту не выполнялись.",
        "- Наличие документа не подтверждает конкретный артикул в Молдове и достоверность характеристик.",
        "- Слова производителя не считаются независимыми испытаниями.",
        "- Цены, нормы, формулы и категории качества не изменены.",
        "- Автоматическая публикация остаётся выключенной.",
        "",
    ]

    return "\n".join(lines)


def main():
    report = build_report(
        read_json(FAMILY_FILE),
        read_json(PRIORITY_FILE),
        read_json(LEADS_FILE),
        read_json(QUEUE_FILE),
    )

    Path(REPORT_FILE).write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    markdown = make_markdown(report)

    Path(MARKDOWN_FILE).write_text(
        markdown,
        encoding="utf-8",
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as output:
            output.write(markdown + "\n")

    print("=== COSTARO STAGE 39: BULK SOURCE AUDIT ===")

    for key, value in report["summary"].items():
        print(f"{key}: {value}")

    print(
        "Read-only: prices, formulas, consumption norms, "
        "quality tiers and publication flags unchanged."
    )


if __name__ == "__main__":
    main()