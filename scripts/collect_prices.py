import json
import re
import statistics
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


SOURCE_FILE = Path("price_sources.json")
REPORT_FILE = Path("price_observations.json")

ALLOWED_DOMAINS = {
    "stroimarket.md",
    "www.stroimarket.md",
    "www.obramag.md",
    "obramag.md",
    "teremok.md",
    "www.teremok.md",
}


class PageTextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.ignored += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self.ignored:
            self.ignored -= 1

    def handle_data(self, data):
        if not self.ignored:
            value = " ".join(data.split())
            if value:
                self.parts.append(value)


def download_page(url):
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("Only HTTPS sources are allowed")

    if parsed.hostname not in ALLOWED_DOMAINS:
        raise ValueError("Source domain is not approved")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "COSTARO-PriceResearch/0.1",
            "Accept": "text/html",
        },
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        final_url = response.geturl()
        final_domain = urlparse(final_url).hostname

        if final_domain not in ALLOWED_DOMAINS:
            raise ValueError("Unexpected redirect domain")

        content_type = response.headers.get("Content-Type", "")

        if "text/html" not in content_type.lower():
            raise ValueError("Unexpected content type")

        raw = response.read(2_000_001)

        if len(raw) > 2_000_000:
            raise ValueError("Page is too large")

        return raw.decode("utf-8", errors="replace")


def normalize(value):
    return re.sub(r"\s+", " ", value).strip().lower()


def find_price(html, product_name):
    parser = PageTextParser()
    parser.feed(html)

    parts = parser.parts
    wanted = normalize(product_name)

    matches = []

    for index, text in enumerate(parts):
        if wanted not in normalize(text):
            continue

        # Ищем цену рядом с названием товара.
        nearby = parts[index + 1:index + 16]
        fragment = " ".join(nearby)

        # Если рядом начинается другой товар,
        # не используем его цену.
        fragment = re.split(
            r"\b(?:Cod|Код)\s*:\s*\d+",
            fragment,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]

        candidates = re.findall(
            r"(?<!\d)(\d{1,5}(?:[.,]\d{1,2})?)"
            r"\s*(?:MDL|lei|ле[йя])\b",
            fragment,
            flags=re.IGNORECASE,
        )

        for candidate in candidates:
            price = float(candidate.replace(",", "."))

            if 10 <= price <= 2000:
                matches.append(price)

    # При неоднозначности цену не принимаем.
    unique = sorted(set(matches))

    if len(unique) == 1:
        return unique[0], "candidate"

    if not unique:
        return None, "unavailable"

    return None, "ambiguous"


def main():
    with SOURCE_FILE.open("r", encoding="utf-8") as file:
        config = json.load(file)

    if config.get("automaticPublicationEnabled") is not False:
        raise ValueError("Automatic publication must remain disabled")

    if config.get("country") != "MD":
        raise ValueError("Unexpected country")

    if config.get("currency") != "MDL":
        raise ValueError("Unexpected currency")

    report = {
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "country": "MD",
        "currency": "MDL",
        "mode": "observation_only",
        "materials": [],
    }

    for material in config["materials"]:
        observations = []

        for source in material["sources"]:
            observation = {
                "store": source["store"],
                "url": source["url"],
                "productCode": source["productCode"],
                "price": None,
                "status": "unavailable",
            }

            try:
                html = download_page(source["url"])
                price, status = find_price(
                    html,
                    material["name"],
                )

                observation["price"] = price
                observation["status"] = status

            except (
                ValueError,
                TimeoutError,
                urllib.error.URLError,
                UnicodeError,
            ) as error:
                observation["status"] = "unavailable"
                observation["error"] = type(error).__name__

            observations.append(observation)

            print(
                f"{source['store']}: "
                f"{observation['status']} "
                f"{observation['price']}"
            )

        prices = [
            item["price"]
            for item in observations
            if item["status"] == "candidate"
            and item["price"] is not None
        ]

        material_result = {
            "id": material["id"],
            "name": material["name"],
            "observations": observations,
            "candidateMedian": (
                statistics.median(prices)
                if len(prices) >= 2
                else None
            ),
            "readyForPublication": False,
        }

        report["materials"].append(material_result)

    with REPORT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Report saved: {REPORT_FILE}")
    print("Published prices were NOT changed.")


if __name__ == "__main__":
    main()
