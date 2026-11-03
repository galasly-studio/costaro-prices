import json
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

OFFICIAL = {
    "startPutty": (
        "https://www.sniezka.md/produs/acryl-putz-st-10-start",
        "Проверить совпадение ST10 START и упаковки 20 кг."
    ),
    "decorativePlaster": (
        "https://policolor.ro/wp-content/uploads/fise/vinarom-tencuiala-decorativa-alba/VINAROM%20TENCUIALA_new.pdf",
        "Проверить вариант F15, цвет и точную рецептуру."
    ),
    "electricalSocketPerPiece": (
        "https://www.se.com/ro/ro/product/EPH2900221/asfora-priza-simpla-2p%2Be-16a-obturatoare-alb/",
        "Проверить артикул EPH2900221 и параметры установки."
    ),
    "floorWaterproofing": (
        "https://www.ceresit.ro/produse/solutii-pentru-placari/produs.html/ceresit-cl-51/SAP_0201SKC013R0.html",
        "Проверить CL 51 Express, условия применения и упаковку."
    ),
    "finishPutty": (
        "https://supraten.md/shpatlevka-mesterul-manole-8kg-54800-ru",
        "Проверить Meșterul Manole 8 кг и расход."
    ),
    "grout": (
        "https://www.ceresit.md/produse/produse-pentru-placari/chituri-flexibile/produse.html/ceresit-ce-40/SAP_0201SGC013M9/variation/1488227.html",
        "Проверить CE 40, вариант цвета и упаковку 2 кг."
    ),
    "gypsumBoardCeiling": (
        "https://www.technogipspro.com/products/standartna-gipsokartonena-ploskost-tip-a",
        "Документ относится к типу A; точный товарный артикул ещё не установлен."
    ),
    "floorScreedMix": (
        "https://www.kreisel.pl/en/product/cement-groundwork-m-15-441-cement-universal-floor-underlay-25-80-mm",
        "ВАЖНО: у молдавского предложения указан диапазон 10–60 мм, у найденной документации — 25–80 мм. Проверить региональную версию."
    ),
    "selfLevelingFloorMix": (
        "https://supraten.md/sapa-autonivelanta-nivelir-universal-25kg-225111-ro",
        "Проверить Nivelir Universal 25 кг и допустимую толщину."
    ),
    "cementPlaster": (
        "https://supraten.md/supraten-optim-25kg-ro",
        "Проверить Optim 25 кг, назначение и расход без изменения норм COSTARO."
    ),
    "gypsumPlaster": (
        "https://supraten.md/tencuiala-pe-baza-de-gips-orizont-30kg-54871-ro",
        "Проверить Orizont 30 кг и допустимые основания."
    ),
    "interiorPaint": (
        "https://supraten.md/kraska-romanita-7kg-54889-ru",
        "ВАЖНО: Romanita предназначена для сухих помещений; нельзя автоматически назначать для всех типов комнат."
    ),
    "primer": (
        "https://supraten.md/grund-supraton-extra-3kg-54766-ro",
        "Проверить Supraton Extra 3 кг и совместимость оснований."
    ),
    "tileAdhesive": (
        "https://supraten.md/adeziv-class-nas-25kg-54878-ro",
        "Проверить Class Naș 25 кг и пригодность для влажных помещений."
    ),
}

TRUSTED_HOSTS = {
    "sniezka.md",
    "policolor.ro",
    "se.com",
    "ceresit.ro",
    "ceresit.md",
    "supraten.md",
    "technogipspro.com",
    "kreisel.pl",
}

HIGH_PRIORITY = {"floorScreedMix", "interiorPaint"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalized_host(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    return parsed.hostname.lower().removeprefix("www.")


def probe_official_source(url):
    host = normalized_host(url)
    if host not in TRUSTED_HOSTS:
        return "rejected_untrusted_url"

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Costaro-Research-Audit/1.0",
            "Accept": "text/html,application/pdf",
        },
    )

    opener = urllib.request.build_opener(NoRedirect())

    try:
        with opener.open(request, timeout=8) as response:
            content_type = response.headers.get(
                "Content-Type", ""
            ).lower()

            prefix = response.read(4096)

            if "pdf" in content_type:
                if prefix.startswith(b"%PDF-"):
                    return "reachable_pdf_format_only"
                return "document_format_mismatch"

            if "html" in content_type:
                if prefix.strip():
                    return "reachable_html_format_only"
                return "empty_document"

            return "unexpected_content_type"

    except urllib.error.HTTPError as error:
        if error.code in (403, 429):
            return "http_blocked"

        if 300 <= error.code < 400:
            return "redirect_requires_manual_review"

        return f"http_{error.code}"

    except (
        urllib.error.URLError,
        TimeoutError,
        ConnectionError,
        OSError,
    ):
        return "network_unavailable"


def audit(data, probe=probe_official_source):
    if not isinstance(data, dict):
        raise ValueError("Invalid Stage 42 evidence")

    for field in (
        "publishedPricesChanged",
        "flutterCalculationsChanged",
        "consumptionNormsChanged",
        "automaticPublicationEnabled",
        "automaticTierAssignmentEnabled",
    ):
        if data.get(field) is not False:
            raise ValueError(f"Unsafe Stage 42 flag: {field}")

    candidates = data.get("candidates", [])
    if not isinstance(candidates, list) or len(candidates) < 23:
        raise ValueError("Incomplete Stage 42 candidate coverage")

    keys = [
        candidate.get("catalogMaterialKey")
        for candidate in candidates
    ]

    if len(keys) != len(set(keys)):
        raise ValueError("Duplicated candidate material keys")

    if not set(OFFICIAL).issubset(set(keys)):
        raise ValueError("Official source registry does not match Stage 42")

    host_groups = defaultdict(list)

    for key, (url, _) in OFFICIAL.items():
        host = normalized_host(url)
        if host not in TRUSTED_HOSTS:
            raise ValueError(f"Untrusted source for {key}")
        host_groups[host].append((key, url))

    def scan_host(group):
        results = {}
        blocked = False

        for key, url in group:
            if blocked:
                results[key] = "skipped_after_host_block"
                continue

            status = probe(url)
            results[key] = status

            if status == "http_blocked":
                blocked = True

        return results

    observed = {}

    with ThreadPoolExecutor(max_workers=3) as executor:
        for result in executor.map(
            scan_host, host_groups.values()
        ):
            observed.update(result)

    records = []

    for candidate in candidates:
        key = candidate["catalogMaterialKey"]
        configured_name = candidate.get(
            "configuredProductName", key
        )

        if key in OFFICIAL:
            url, note = OFFICIAL[key]
            availability = observed[key]
            source_kind = (
                "official_pdf_lead"
                if urlsplit(url).path.lower().endswith(".pdf")
                else "official_company_page_lead"
            )
        else:
            url = None
            note = (
                "Не установлен официальный производитель "
                "точной товарной модели."
            )
            availability = "official_source_not_identified"
            source_kind = None

        records.append({
            "catalogMaterialKey": key,
            "configuredProductName": configured_name,
            "sourceKind": source_kind,
            "officialSourceLeadUrl": url,
            "sourceAvailability": availability,
            "manualReviewNoteRu": note,
            "highPriorityTechnicalReview": key in HIGH_PRIORITY,
            "exactManufacturerModelIndependentlyVerified": False,
            "technicalCriteriaIndependentlyVerified": False,
            "qualityTierApproved": False,
            "priceChangeApproved": False,
            "manualReviewRequired": True,
        })

    reachable = sum(
        r["sourceAvailability"] in (
            "reachable_html_format_only",
            "reachable_pdf_format_only",
        )
        for r in records
    )

    report = {
        "schemaVersion": 1,
        "status": "official_source_research_only",
        "generatedAtUtc": datetime.now(
            timezone.utc
        ).isoformat(),
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "automaticPublicationEnabled": False,
        "automaticTierAssignmentEnabled": False,
        "summary": {
            "researchCandidates": len(candidates),
            "officialSourceLeads": len(OFFICIAL),
            "withoutOfficialSourceLead": (
                len(candidates) - len(OFFICIAL)
            ),
            "reachableSourceFormatsOnly": reachable,
            "highPriorityTechnicalConflictsToReview": sum(
                r["highPriorityTechnicalReview"]
                for r in records
            ),
            "independentlyVerifiedManufacturerModels": 0,
            "approvedQualityTiers": 0,
            "approvedPriceChanges": 0,
        },
        "records": records,
    }

    return report


def write_reports(report):
    Path("official_source_batch_review.json").write_text(
        json.dumps(
            report, ensure_ascii=False, indent=2
        ) + "\n",
        encoding="utf-8",
    )

    ordered = sorted(
        report["records"],
        key=lambda row: (
            0 if row["highPriorityTechnicalReview"] else 1,
            0 if row["officialSourceLeadUrl"] is None else 1,
            row["catalogMaterialKey"],
        ),
    )

    queue = {
        "status": "manual_research_only",
        "automaticPublicationEnabled": False,
        "items": ordered,
    }

    Path("official_source_batch_queue.json").write_text(
        json.dumps(
            queue, ensure_ascii=False, indent=2
        ) + "\n",
        encoding="utf-8",
    )

    summary = report["summary"]

    lines = [
        "# COSTARO — этап 43: официальные источники",
        "",
        "**Исследование, а не подтверждение качества или цены.**",
        "",
        f"- Товарных групп: **{summary['researchCandidates']}**.",
        f"- Найденных официальных источников: **{summary['officialSourceLeads']}**.",
        f"- Без официального источника: **{summary['withoutOfficialSourceLead']}**.",
        f"- Доступных форматов страниц/PDF: **{summary['reachableSourceFormatsOnly']}**.",
        f"- Приоритетных технических вопросов: **{summary['highPriorityTechnicalConflictsToReview']}**.",
        "- Независимо подтверждённых моделей: **0**.",
        "- Утверждённых категорий качества: **0**.",
        "- Разрешённых изменений цен: **0**.",
        "",
        "Доступность HTML или PDF **не подтверждает** "
        "соответствие точной модели, достоверность "
        "характеристик или качество материала.",
        "",
        "| Материал | Источник | Результат | Ручная проверка |",
        "|---|---|---|---|",
    ]

    for record in ordered:
        name = record["configuredProductName"].replace("|", "/")
        url = record["officialSourceLeadUrl"]

        source = (
            f"[Страница/PDF]({url})"
            if url
            else "Не найден"
        )

        note = record["manualReviewNoteRu"].replace("|", "/")

        lines.append(
            f"| {name} | {source} | "
            f"`{record['sourceAvailability']}` | {note} |"
        )

    lines.extend([
        "",
        "## Обязательные ограничения",
        "",
        "- Сведения компании-производителя не являются "
        "независимым испытанием.",
        "- Товар без подтверждённого производителя "
        "не получает категорию качества.",
        "- Kreisel 441 требует сверки региональной "
        "документации и точной упаковки.",
        "- Romanita не назначается автоматически "
        "для влажных помещений.",
        "- Применимость материала и расход "
        "проверяются отдельно.",
        "- Цены, нормы, формулы и существующие "
        "категории качества COSTARO не изменены.",
        "- Автоматическая публикация отключена.",
        "",
    ])

    Path("official_source_batch_review_RU.md").write_text(
        "\n".join(lines),
        encoding="utf-8",
    )


def main():
    source = Path("bulk_sku_quality_evidence.json")

    if not source.is_file():
        raise SystemExit(
            "Stage 42 report missing; execution order invalid"
        )

    data = json.loads(source.read_text(encoding="utf-8"))
    report = audit(data)
    write_reports(report)

    s = report["summary"]

    print(
        "COSTARO STAGE 43: "
        f"{s['researchCandidates']} materials, "
        f"{s['officialSourceLeads']} official source leads, "
        f"{s['withoutOfficialSourceLead']} without leads."
    )
    print(
        "Approved quality tiers: 0. "
        "Approved price changes: 0. "
        "Automatic publication: OFF."
    )


if __name__ == "__main__":
    main()