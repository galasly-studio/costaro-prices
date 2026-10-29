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
    "macons.md",
    "www.macons.md",
    "gebhardt.md",
    "www.gebhardt.md",
    "teremok.md",
    "www.teremok.md",
}


class ProductPageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.text_parts = []
        self.json_ld = []
        self.meta_prices = []
        self.inside_script = False
        self.inside_style = False
        self.script_is_json_ld = False
        self.script_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag == "style":
            self.inside_style = True

        if tag == "script":
            self.inside_script = True
            script_type = attributes.get("type", "").lower()
            self.script_is_json_ld = (
                script_type == "application/ld+json"
            )
            self.script_parts = []

        if tag == "meta":
            key = (
                attributes.get("property")
                or attributes.get("name")
                or ""
            ).lower()

            if key in {
                "product:price:amount",
                "og:price:amount",
            }:
                value = attributes.get("content", "")
                if value:
                    self.meta_prices.append(value)

    def handle_endtag(self, tag):
        if tag == "style":
            self.inside_style = False

        if tag == "script":
            if self.script_is_json_ld:
                content = "".join(self.script_parts).strip()

                if content:
                    try:
                        self.json_ld.append(json.loads(content))
                    except json.JSONDecodeError:
                        pass

            self.inside_script = False
            self.script_is_json_ld = False
            self.script_parts = []

    def handle_data(self, data):
        if self.inside_script:
            if self.script_is_json_ld:
                self.script_parts.append(data)
            return

        if self.inside_style:
            return

        value = " ".join(data.split())

        if value:
            self.text_parts.append(value)


def normalize(value):
    value = str(value).lower()
    value = value.replace("naș", "nas")
    value = value.replace("naş", "nas")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def valid_product_name(value):
    name = normalize(value)

    return (
        "class nas" in name
        and re.search(r"25\s*kg\b", name) is not None
    )


def parse_price(value):
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        number = float(value)

    elif isinstance(value, str):
        cleaned = value.strip().replace(" ", "")
        cleaned = cleaned.replace("\u00a0", "")
        cleaned = cleaned.replace(",", ".")

        if not re.fullmatch(r"\d+(?:\.\d{1,2})?", cleaned):
            return None

        number = float(cleaned)

    else:
        return None

    if 10 <= number <= 2000:
        return round(number, 2)

    return None


def download_page(url):
    parsed = urlparse(url)

    if parsed.scheme != "https":
        raise ValueError("Only HTTPS sources are allowed")

    if parsed.hostname not in ALLOWED_DOMAINS:
        raise ValueError("Unapproved source domain")

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 "
                "(compatible; COSTARO-PriceResearch/0.2)"
            ),
            "Accept": "text/html",
        },
    )

    with urllib.request.urlopen(request, timeout=20) as response:
        final_url = response.geturl()

        if urlparse(final_url).hostname not in ALLOWED_DOMAINS:
            raise ValueError("Unexpected redirect")

        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        if "text/html" not in content_type:
            raise ValueError("Response is not HTML")

        raw = response.read(2_000_001)

        if len(raw) > 2_000_000:
            raise ValueError("Page exceeds size limit")

        return raw.decode("utf-8", errors="replace")


def find_product_objects(value):
    results = []

    if isinstance(value, list):
        for item in value:
            results.extend(find_product_objects(item))

    elif isinstance(value, dict):
        object_type = value.get("@type", "")
        types = (
            object_type
            if isinstance(object_type, list)
            else [object_type]
        )

        if "Product" in types:
            results.append(value)

        for nested in value.values():
            if isinstance(nested, (list, dict)):
                results.extend(find_product_objects(nested))

    return results


def structured_prices(parser, expected_code):
    prices = []

    for block in parser.json_ld:
        for product in find_product_objects(block):
            if not valid_product_name(
                product.get("name", "")
            ):
                continue

            sku = str(product.get("sku", "")).strip()

            if sku and sku != expected_code:
                continue

            offers = product.get("offers", [])

            if isinstance(offers, dict):
                offers = [offers]

            if not isinstance(offers, list):
                continue

            for offer in offers:
                if not isinstance(offer, dict):
                    continue

                currency = offer.get("priceCurrency")

                if currency and currency != "MDL":
                    continue

                price = parse_price(offer.get("price"))

                if price is not None:
                    prices.append(price)

    return sorted(set(prices))


def visible_prices(parser):
    parts = parser.text_parts

    # Требуем название товара на странице.
    if not any(valid_product_name(part) for part in parts):
        return []

    prices = []
    price_pattern = re.compile(
        r"(?<!\d)(\d{1,5}(?:[.,]\d{1,2})?)"
        r"\s*(?:MDL|lei)\b",
        re.IGNORECASE,
    )

    for index, part in enumerate(parts):
        if not valid_product_name(part):
            continue

        # Ищем только в небольшом фрагменте
        # после названия конкретного товара.
        fragment_parts = parts[index + 1:index + 16]

        for text in fragment_parts:
            if valid_product_name(text):
                break

            for match in price_pattern.findall(text):
                price = parse_price(match)

                if price is not None:
                    prices.append(price)

    return sorted(set(prices))


def inspect_page(html, expected_code):
    parser = ProductPageParser()
    parser.feed(html)

    full_text = normalize(" ".join(parser.text_parts))

    if not valid_product_name(full_text):
        return None, "product_not_found", "none"

    structured = structured_prices(
        parser,
        expected_code,
    )

    if len(structured) == 1:
        return structured[0], "candidate", "structured_data"

    if len(structured) > 1:
        return None, "ambiguous", "structured_data"

    visible = visible_prices(parser)

    if len(visible) == 1:
        return visible[0], "candidate", "visible_text"

    if len(visible) > 1:
        return None, "ambiguous", "visible_text"

    # Мета-теги проверяем только как дополнительный
    # источник, без автоматического подтверждения цены.
    return None, "unavailable", "none"


def main():
    with SOURCE_FILE.open("r", encoding="utf-8") as file:
        config = json.load(file)

    if config.get("schemaVersion") != 1:
        raise ValueError("Unsupported source schema")

    if config.get("country") != "MD":
        raise ValueError("Unexpected country")

    if config.get("currency") != "MDL":
        raise ValueError("Unexpected currency")

    if config.get("automaticPublicationEnabled") is not False:
        raise ValueError(
            "Automatic publication must remain disabled"
        )

    materials = config.get("materials")

    if not isinstance(materials, list) or not materials:
        raise ValueError("Materials list is missing")

    report = {
        "generatedAt": datetime.now(
            timezone.utc
        ).isoformat(),
        "country": "MD",
        "currency": "MDL",
        "mode": "observation_only",
        "materials": [],
    }

    for material in materials:
        observations = []

        for source in material["sources"]:
            observation = {
                "store": source["store"],
                "url": source["url"],
                "productCode": source["productCode"],
                "price": None,
                "status": "unavailable",
                "extractionMethod": "none",
            }

            try:
                html = download_page(source["url"])

                price, status, method = inspect_page(
                    html,
                    str(source["productCode"]),
                )

                observation["price"] = price
                observation["status"] = status
                observation["extractionMethod"] = method

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
                f"{observation['status']} | "
                f"{observation['price']} MDL | "
                f"{observation['extractionMethod']}"
            )

        candidates = [
            item["price"]
            for item in observations
            if item["status"] == "candidate"
            and item["price"] is not None
        ]

        median = None

        if len(candidates) >= 2:
            low = min(candidates)
            high = max(candidates)

            # При слишком большом расхождении
            # предварительную медиану не рассчитываем.
            if high <= low * 1.20:
                median = statistics.median(candidates)

        report["materials"].append(
            {
                "id": material["id"],
                "name": material["name"],
                "observations": observations,
                "candidateMedian": median,
                "readyForPublication": False,
            }
        )

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
