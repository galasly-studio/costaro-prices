"""Read-only live research of one Moldova retail SKU listing."""

import json
import os
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


MANUFACTURER_URL = "https://supraten.md/nas-baund-25kg-ro"

RETAILER_URL = (
    "https://casa24.md/ro/produs/"
    "adeziv-pentru-faianta-class-nas-baund-25-kg-ro/"
)

EXPECTED_ARTICLE = "510027"
MAX_PAGE_BYTES = 1_500_000


class VisibleTextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def visible_text(html):
    parser = VisibleTextParser()
    parser.feed(html)

    text = unicodedata.normalize(
        "NFKC", " ".join(parser.parts)
    )

    return re.sub(r"\s+", " ", text).strip()


def fetch_page(url):
    """One public HTTPS request. No retries or access bypass."""
    parsed = urlsplit(url)

    if parsed.scheme != "https" or parsed.hostname not in {
        "supraten.md",
        "casa24.md",
    }:
        raise ValueError("Source host is not approved.")

    request = Request(
        url,
        headers={
            "User-Agent": "COSTARO-Research-Audit/1.0",
            "Accept": "text/html",
            "Accept-Encoding": "identity",
        },
    )

    with urlopen(request, timeout=8) as response:
        if response.status != 200:
            raise ValueError("Unexpected HTTP status.")

        final_host = urlsplit(response.geturl()).hostname

        if final_host != parsed.hostname:
            raise ValueError("Unexpected cross-domain redirect.")

        if response.headers.get_content_type() != "text/html":
            raise ValueError("Unexpected content type.")

        data = response.read(MAX_PAGE_BYTES + 1)

        if len(data) > MAX_PAGE_BYTES:
            raise ValueError("Response exceeds size limit.")

        encoding = (
            response.headers.get_content_charset()
            or "utf-8"
        )

        return data.decode(encoding, errors="replace")


def inspect_manufacturer(text):
    article = bool(
        re.search(
            r"\bArticol\s*:\s*510027\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    product = bool(
        re.search(
            r"\bAdeziv\s+Nas\s+Baund\s*25\s*kg\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    return {
        "articleObserved": article,
        "nameAndPackObserved": product,
        "pageMatch": article and product,
    }


def inspect_retailer(text):
    article = bool(
        re.search(
            r"\bCod\s+produs\s*:\s*510027\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    product = bool(
        re.search(
            r"\bNas\s+Baund\s+25\s*kg\b",
            text,
            flags=re.IGNORECASE,
        )
    )

    stock = re.search(
        r"\b(\d{1,4})\s+(?:în|in)\s+stoc\b",
        text,
        flags=re.IGNORECASE,
    )

    listed_units = int(stock.group(1)) if stock else None

    return {
        "articleObserved": article,
        "nameAndPackObserved": product,
        "pageMatch": article and product,
        "retailerListedUnits": listed_units,
        "retailerClaimsPositiveStock": (
            listed_units is not None and listed_units > 0
        ),
        "physicalStockVerified": False,
    }


def build_report(provenance, fetcher=fetch_page, now=None):
    now = now or datetime.now(timezone.utc)

    if provenance.get("status") != (
        "manual_product_provenance_review_only"
    ):
        raise ValueError("Unexpected Stage 37 provenance status.")

    previous = provenance.get("summary", {})

    if (
        previous.get("manufacturerArticleCrossReferencesDocumented") != 1
        or previous.get("unresolvedSkuTasks") != 8
    ):
        raise ValueError("Stage 37 baseline changed.")

    observations = []

    for name, url, inspector in (
        ("SUPRATEN", MANUFACTURER_URL, inspect_manufacturer),
        ("Casa24", RETAILER_URL, inspect_retailer),
    ):
        row = {
            "source": name,
            "url": url,
            "httpFetched": False,
            "pageMatch": False,
            "articleObserved": False,
            "nameAndPackObserved": False,
            "accessError": None,
        }

        try:
            html = fetcher(url)
            text = visible_text(html)
            row.update(inspector(text))
            row["httpFetched"] = True
        except (OSError, ValueError, UnicodeError) as error:
            row["accessError"] = type(error).__name__

        observations.append(row)

    manufacturer, retailer = observations

    both_match = bool(
        manufacturer["pageMatch"] and retailer["pageMatch"]
    )

    listed_stock = (
        retailer.get("retailerClaimsPositiveStock", False)
        if both_match
        else False
    )

    if both_match:
        state = "same_article_and_pack_observed_on_two_live_pages"
    elif any(row["accessError"] for row in observations):
        state = "source_access_failed_manual_review"
    else:
        state = "listing_mismatch_manual_review"

    return {
        "schemaVersion": 1,
        "status": "read_only_live_sku_research",
        "checkedAtUtc": now.isoformat(),
        "catalogMaterialKey": "tileAdhesive",
        "researchProduct": "SUPRATEN NAS BAUND 25 kg",
        "manufacturerArticle": EXPECTED_ARTICLE,
        "observationState": state,
        "sourceObservations": observations,
        "summary": {
            "sourcesConfigured": 2,
            "sourcesFetched": sum(
                row["httpFetched"] for row in observations
            ),
            "sameArticleAndPackOnLivePages": both_match,
            "retailerClaimsPositiveStock": listed_stock,
            "retailerListedUnits": (
                retailer.get("retailerListedUnits")
                if both_match
                else None
            ),
            "physicalStockVerified": False,
            "manufacturerConfirmedEAN": False,
            "currentBatchTechnicalDataVerified": False,
            "technicalTemperatureConflictResolved": False,
            "unresolvedSkuResearchTasks": 8,
            "fullyClosedSkuTasks": 0,
            "qualityTiersApproved": 0,
            "approvedForPublication": 0,
        },
        "publishedPricesChanged": False,
        "flutterCalculationsChanged": False,
        "consumptionNormsChanged": False,
        "tierMappingsChanged": False,
        "automaticTierAssignmentEnabled": False,
        "automaticPublicationEnabled": False,
    }


def render_markdown(report):
    summary = report["summary"]

    lines = [
        "# COSTARO — онлайн-проверка SKU, этап 38",
        "",
        f"Проверено UTC: {report['checkedAtUtc']}.",
        "",
        f"Состояние: `{report['observationState']}`.",
        "",
        "| Источник | Доступен | Артикул | Название и упаковка |",
        "|---|---|---|---|",
    ]

    for row in report["sourceObservations"]:
        lines.append(
            f"| {row['source']} "
            f"| {'Да' if row['httpFetched'] else 'Нет'} "
            f"| {'Да' if row['articleObserved'] else 'Нет'} "
            f"| {'Да' if row['nameAndPackObserved'] else 'Нет'} |"
        )

    lines.extend([
        "",
        "## Результат",
        "",
        "Совпадение артикула и упаковки на двух страницах: "
        + (
            "**да**."
            if summary["sameArticleAndPackOnLivePages"]
            else "**не подтверждено**."
        ),
        "",
        "Положительный остаток, заявленный магазином: "
        + (
            "**да**."
            if summary["retailerClaimsPositiveStock"]
            else "**не подтверждён**."
        ),
        "",
        "Заявленное количество: "
        + (
            str(summary["retailerListedUnits"])
            if summary["retailerListedUnits"] is not None
            else "не установлено"
        )
        + ".",
        "",
        "**Важно:** данные сайта не являются независимым "
        "подтверждением физического наличия.",
        "",
        "Не подтверждены: EAN производителем, партия, "
        "актуальный техпаспорт продаваемой упаковки "
        "и спорная температурная характеристика.",
        "",
        f"Полностью закрытых задач SKU: "
        f"**{summary['fullyClosedSkuTasks']}**.",
        "",
        "Цены, нормы, формулы и категории качества "
        "не изменены. Автоматическая публикация отключена.",
        "",
    ])

    return "\n".join(lines)


def main():
    provenance = json.loads(
        Path("product_provenance_review.json").read_text(
            encoding="utf-8"
        )
    )

    report = build_report(provenance)
    markdown = render_markdown(report)

    Path("live_sku_listing_check.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    Path("live_sku_listing_check_RU.md").write_text(
        markdown,
        encoding="utf-8",
    )

    print(
        "COSTARO Stage 38: "
        f"{report['observationState']}; "
        "0 price changes; 0 tier approvals."
    )

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")

    if summary_path:
        with Path(summary_path).open(
            "a", encoding="utf-8"
        ) as output:
            output.write(markdown + "\n")


if __name__ == "__main__":
    main()
