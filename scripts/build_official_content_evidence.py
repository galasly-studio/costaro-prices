"""Research-only, bounded content review of exact manufacturer source leads.

Does not approve a material, infer a quality tier, or touch prices.json.
An official company's statement is not an independent laboratory test.
"""

import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

# GitHub Actions runs this as `python3 scripts/...py`, while unit tests import
# it as a package. Both paths must resolve the same checked-in source module.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_official_manufacturer_batch import (
    NoRedirect,
    OFFICIAL,
    TRUSTED_HOSTS,
    normalized_host,
)


MAX_DOCUMENT_BYTES = 3_000_000

# Each tuple contains required groups of acceptable spellings. A positive match
# only means that the company page mentions the model family; it is NOT proof
# of the exact Moldovan item, batch, packaging, testing, or price tier.
MODEL_SIGNALS = {
    "startPutty": (("acryl putz", "acrylputz"), ("st10", "st 10")),
    "decorativePlaster": (("vinarom",), ("f15", "f 15")),
    "electricalSocketPerPiece": (("asfora",), ("eph2900221",)),
    "floorWaterproofing": (("ceresit",), ("cl51", "cl 51")),
    "finishPutty": (("mesterul manole",),),
    "grout": (("ceresit",), ("ce40", "ce 40")),
    "gypsumBoardCeiling": (("technogips",), ("type a", "tip a", "тип a")),
    "floorScreedMix": (("kreisel",), ("441",)),
    "selfLevelingFloorMix": (("nivelir",), ("universal",)),
    "cementPlaster": (("optim",),),
    "gypsumPlaster": (("orizont",),),
    "interiorPaint": (("romanita",),),
    "primer": (("supraton",), ("extra",)),
    "tileAdhesive": (("class",), ("nas",)),
}

# A pack/size mention on a general product page is only a research hint: the
# manufacturer may offer several packages or regional product variants.
FORMAT_SIGNALS = {
    "startPutty": ("20 kg", "20kg"),
    "decorativePlaster": ("25 kg", "25kg"),
    "electricalSocketPerPiece": ("16 a", "16a"),
    "floorWaterproofing": ("5 kg", "5kg"),
    "finishPutty": ("8 kg", "8kg"),
    "grout": ("2 kg", "2kg"),
    "gypsumBoardCeiling": ("12 5 mm", "12 5mm"),
    "floorScreedMix": ("25 kg", "25kg"),
    "selfLevelingFloorMix": ("25 kg", "25kg"),
    "cementPlaster": ("25 kg", "25kg"),
    "gypsumPlaster": ("30 kg", "30kg"),
    "interiorPaint": ("7 kg", "7kg"),
    "primer": ("3 kg", "3kg"),
    "tileAdhesive": ("25 kg", "25kg"),
}

# Technical vocabulary is used only to locate potentially relevant sections.
# The presence of any word never satisfies a technical requirement.
TOPIC_PATTERNS = {
    "roomUse": r"\b(?:interior|exterior|incaperi|помещени|indoor|outdoor|humidity|umiditat)\w*",
    "thickness": r"\b(?:grosime|thickness|толщин|grubosc|layer)\w*",
    "consumption": r"\b(?:consum|consumption|расход|zuzycie)\w*",
    "substrates": r"\b(?:substrat|suport|основан|substrate|podloz)\w*",
    "drying": r"\b(?:uscar|drying|высыхан|schnię|schnie)\w*",
    "installation": r"\b(?:aplicar|instalar|installation|montaj|montaz|укладк)\w*",
    "strength": r"\b(?:rezistent|strength|прочност|wytrzymal)\w*",
}

CRITICAL_REVIEW_KEYS = {"interiorPaint", "floorScreedMix"}


def normalize(value):
    value = unicodedata.normalize("NFKD", str(value)).casefold()
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[\w]+", value, re.UNICODE))


def contains_alias(normalized_text, alias):
    token = normalize(alias)
    return bool(token) and bool(re.search(r"(?<!\w)" + re.escape(token) + r"(?!\w)", normalized_text))


def source_text_from_html(raw):
    # Don't run JavaScript, scripts, or CSS. Keep plain text only; bound memory.
    value = raw.decode("utf-8", errors="replace")
    value = re.sub(r"(?is)<(?:script|style|noscript)\b[^>]*>.*?</(?:script|style|noscript)>", " ", value)
    value = re.sub(r"(?s)<[^>]+>", " ", value)
    return html.unescape(value)


def source_text_from_pdf(raw):
    command = shutil.which("pdftotext")
    if not command:
        return None, "pdf_text_tool_unavailable"
    try:
        process = subprocess.run(
            [command, "-", "-"],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=12,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None, "pdf_text_extraction_failed"
    if process.returncode != 0 or not process.stdout.strip():
        return None, "pdf_text_extraction_failed"
    return process.stdout.decode("utf-8", errors="replace"), "text_extracted_pdf"


def fetch_document(url):
    """One GET, no redirects or retries. Blocked hosts get skipped by caller."""
    if normalized_host(url) not in TRUSTED_HOSTS:
        return {"status": "untrusted_url", "text": "", "sha256": None}

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Costaro-Research-Audit/1.0",
            "Accept": "text/html,application/pdf",
        },
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=9) as response:
            content_type = response.headers.get("Content-Type", "").lower()
            body = response.read(MAX_DOCUMENT_BYTES + 1)
    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            status = "http_blocked"
        elif 300 <= error.code < 400:
            status = "redirect_requires_manual_review"
        else:
            status = f"http_{error.code}"
        return {"status": status, "text": "", "sha256": None}
    except (urllib.error.URLError, TimeoutError, OSError):
        return {"status": "network_unavailable", "text": "", "sha256": None}

    if len(body) > MAX_DOCUMENT_BYTES:
        return {"status": "document_too_large", "text": "", "sha256": None}
    digest = hashlib.sha256(body).hexdigest()
    if "application/pdf" in content_type:
        if not body.startswith(b"%PDF-"):
            return {"status": "pdf_header_mismatch", "text": "", "sha256": digest}
        text, status = source_text_from_pdf(body)
        return {"status": status, "text": text or "", "sha256": digest}
    if "text/html" in content_type:
        text = source_text_from_html(body)
        status = "text_extracted_html" if text.strip() else "empty_html"
        return {"status": status, "text": text, "sha256": digest}
    return {"status": "unexpected_content_type", "text": "", "sha256": digest}


def evaluate_document(key, text, retail_name):
    normalized = normalize(text)
    groups = MODEL_SIGNALS[key]
    groups_found = [any(contains_alias(normalized, alias) for alias in group) for group in groups]
    format_found = any(contains_alias(normalized, alias) for alias in FORMAT_SIGNALS[key])

    topics = {
        name: bool(re.search(pattern, normalized, flags=re.IGNORECASE))
        for name, pattern in TOPIC_PATTERNS.items()
    }

    restrictions = []
    if key == "interiorPaint" and re.search(
        r"(?:сухих помещени|incaperi uscate|dry rooms|dry interior)", normalized
    ):
        restrictions.append("company_text_limits_product_to_dry_rooms")
    if key == "floorScreedMix" and re.search(r"25\s*(?:-|–|to)\s*80", text, re.IGNORECASE):
        if re.search(r"10\s*(?:-|–|to)\s*60", retail_name, re.IGNORECASE):
            restrictions.append("regional_thickness_range_disagreement_10_60_vs_25_80")

    return {
        "modelFamilyMarkersPresent": bool(normalized) and all(groups_found),
        "configuredPackageOrRatingMentioned": bool(normalized) and format_found,
        "requiredMarkerGroupsObserved": groups_found,
        "technicalTopicMentions": topics,
        "technicalRestrictionSignals": restrictions,
        "exactRetailSkuIndependentlyVerified": False,
        "manufacturerTechnicalClaimsIndependentlyTested": False,
    }


def _safe_input(stage42, stage43):
    for report in (stage42, stage43):
        if not isinstance(report, dict):
            raise ValueError("Missing guarded source report")
        for key in (
            "publishedPricesChanged", "flutterCalculationsChanged",
            "consumptionNormsChanged", "automaticPublicationEnabled",
            "automaticTierAssignmentEnabled",
        ):
            if report.get(key) is not False:
                raise ValueError(f"Unsafe report flag: {key}")

    candidates = stage42.get("candidates", [])
    previous = stage43.get("records", [])
    keys = [row.get("catalogMaterialKey") for row in candidates]
    previous_keys = [row.get("catalogMaterialKey") for row in previous]
    if len(keys) < 23 or len(set(keys)) != len(keys) or set(keys) != set(previous_keys):
        raise ValueError("Stage 42/43 coverage mismatch")
    if len(previous_keys) != len(set(previous_keys)):
        raise ValueError("Duplicate Stage 43 keys")
    for row in previous:
        key = row["catalogMaterialKey"]
        expected_url = OFFICIAL.get(key, (None,))[0]
        if row.get("officialSourceLeadUrl") != expected_url:
            raise ValueError(f"Unexpected official source URL: {key}")
    return candidates, {row["catalogMaterialKey"]: row for row in previous}


def audit(stage42, stage43, fetch=fetch_document):
    candidates, previous = _safe_input(stage42, stage43)
    host_groups = defaultdict(list)
    for key, (url, _) in OFFICIAL.items():
        host = normalized_host(url)
        if host not in TRUSTED_HOSTS:
            raise ValueError(f"Untrusted official host: {key}")
        host_groups[host].append((key, url))

    def one_host(rows):
        response = {}
        blocked = False
        for key, url in rows:
            if blocked:
                response[key] = {"status": "skipped_after_host_block", "text": "", "sha256": None}
            else:
                response[key] = fetch(url)
                if response[key]["status"] == "http_blocked":
                    blocked = True
        return response

    fetched = {}
    with ThreadPoolExecutor(max_workers=3) as executor:
        for result in executor.map(one_host, host_groups.values()):
            fetched.update(result)

    records = []
    for item in candidates:
        key = item["catalogMaterialKey"]
        old = previous[key]
        response = fetched.get(key, {"status": "official_source_not_identified", "text": "", "sha256": None})
        checked = evaluate_document(key, response["text"], item.get("configuredProductName", "")) if key in OFFICIAL else None
        records.append({
            "catalogMaterialKey": key,
            "configuredProductName": item.get("configuredProductName", key),
            "officialSourceLeadUrl": old.get("officialSourceLeadUrl"),
            "contentReadStatus": response["status"],
            "contentSha256": response.get("sha256"),
            "companyContentEvidence": checked,
            "technicalReviewPriority": "critical" if key in CRITICAL_REVIEW_KEYS else ("source_missing" if key not in OFFICIAL else "manual"),
            "manualReviewNoteRu": old.get("manualReviewNoteRu", ""),
            "exactRetailSkuIndependentlyVerified": False,
            "approvedQualityTier": None,
            "approvedPriceChange": False,
            "manualReviewRequired": True,
        })

    summary = {
        "catalogResearchCandidates": len(records),
        "officialSourceLeads": len(OFFICIAL),
        "withoutOfficialSource": sum(r["officialSourceLeadUrl"] is None for r in records),
        "companyDocumentTextsExtracted": sum(r["contentReadStatus"].startswith("text_extracted_") for r in records),
        "manufacturerModelFamiliesMentioned": sum(bool((r["companyContentEvidence"] or {}).get("modelFamilyMarkersPresent")) for r in records),
        "companyPagesMentioningConfiguredPackageOrRating": sum(bool((r["companyContentEvidence"] or {}).get("configuredPackageOrRatingMentioned")) for r in records),
        "contentDiscoveredTechnicalRestrictions": sum(bool((r["companyContentEvidence"] or {}).get("technicalRestrictionSignals")) for r in records),
        "independentlyVerifiedExactRetailSkus": 0,
        "independentlyTestedTechnicalCriteria": 0,
        "approvedQualityTiers": 0,
        "approvedPriceChanges": 0,
    }

    return {
        "schemaVersion": 1,
        "status": "manufacturer_document_content_research_only",
        "generatedAtUtc": datetime.now(timezone.utc).isoformat(),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "summary": summary,
        "records": records,
    }


def write_reports(report):
    Path("manufacturer_content_evidence.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    queue = sorted(report["records"], key=lambda row: (
        {"critical": 0, "source_missing": 1, "manual": 2}[row["technicalReviewPriority"]],
        row["catalogMaterialKey"],
    ))
    Path("manufacturer_content_review_queue.json").write_text(
        json.dumps({"status": "manual_review_only", "approvedPriceChanges": 0, "items": queue}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    s = report["summary"]
    lines = [
        "# COSTARO — этап 44: содержание официальных технических источников", "",
        "Это исследование слов и названий в документах компаний, **не** одобрение товара, технологии, качества или цены.", "",
        f"- Товарных групп: **{s['catalogResearchCandidates']}**.",
        f"- Ссылок на компании: **{s['officialSourceLeads']}**.",
        f"- Текстов страниц/PDF удалось прочитать: **{s['companyDocumentTextsExtracted']}**.",
        f"- Упоминаний семейств моделей: **{s['manufacturerModelFamiliesMentioned']}**.",
        f"- Упоминаний упаковки/размера/номинала: **{s['companyPagesMentioningConfiguredPackageOrRating']}**.",
        f"- Без официальной ссылки: **{s['withoutOfficialSource']}**.",
        "- Независимых испытаний и точных сверок артикула: **0**.",
        "- Одобренных уровней качества и изменений цен: **0**.", "",
        "| Товар | Результат чтения | Семейство модели | Ограничения/действие |", "|---|---|---|---|",
    ]
    for row in queue:
        evidence = row["companyContentEvidence"] or {}
        label = "упоминается (не подтверждено)" if evidence.get("modelFamilyMarkersPresent") else "не установлено"
        issues = evidence.get("technicalRestrictionSignals", [])
        note = ", ".join(issues) if issues else row["manualReviewNoteRu"]
        name = row["configuredProductName"].replace("|", "/")
        lines.append(f"| {name} | `{row['contentReadStatus']}` | {label} | {note.replace('|', '/')} |")
    lines.extend([
        "", "## Неизменные ограничения", "",
        "- Слово на странице или PDF не подтверждает конкретный SKU в магазине Молдовы.",
        "- Производительские сведения не равны независимым лабораторным испытаниям.",
        "- Расхождение для Kreisel 441 и ограничение Romanita для сухих помещений требуют проверки человеком.",
        "- Категории бюджет/стандарт/премиум не назначены; цены, расход и Flutter-код не менялись.",
        "- При HTTP 403/429 последующие запросы к хосту в запуске прекращаются; обхода нет.", "",
    ])
    Path("manufacturer_content_evidence_RU.md").write_text("\n".join(lines), encoding="utf-8")
    if os.getenv("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as summary:
            summary.write("\n### COSTARO Stage 44: официальные документы (исследование)\n\n")
            summary.write(f"Текстов: **{s['companyDocumentTextsExtracted']}**, семейств: **{s['manufacturerModelFamiliesMentioned']}**, точных SKU и разрешённых ценовых изменений: **0**.\n\n")


def main():
    path42 = Path("bulk_sku_quality_evidence.json")
    path43 = Path("official_source_batch_review.json")
    if not path42.is_file() or not path43.is_file():
        raise SystemExit("Required Stage 42/43 report missing")
    report = audit(json.loads(path42.read_text(encoding="utf-8")), json.loads(path43.read_text(encoding="utf-8")))
    write_reports(report)
    print("COSTARO STAGE 44:", json.dumps(report["summary"], ensure_ascii=False))
    print("Quality tiers and published prices unchanged; automatic publication OFF.")


if __name__ == "__main__":
    main()
