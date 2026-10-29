"""COSTARO: read-only monitoring of Moldova material prices."""

import json
import re
import statistics
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


SOURCES = Path("price_sources.json")
OUTPUT = Path("price_observations.json")


def normalize(value):
    value = str(value).casefold()
    value = value.replace("naș", "nas").replace("naş", "nas")
    return re.sub(r"\s+", " ", value).strip()


def parse_price(value):
    if isinstance(value, bool):
        return None

    raw = (
        str(value)
        .strip()
        .replace("\u00a0", "")
        .replace(" ", "")
        .replace(",", ".")
    )

    if not re.fullmatch(r"\d+(?:\.\d{1,2})?", raw):
        return None

    price = float(raw)

    if 1 <= price <= 100000:
        return round(price, 2)

    return None


def find_products(node):
    found = []

    if isinstance(node, list):
        for item in node:
            found.extend(find_products(item))

    elif isinstance(node, dict):
        types = node.get("@type", [])

        if isinstance(types, str):
            types = [types]

        if "Product" in types:
            found.append(node)

        for value in node.values():
            if isinstance(value, (dict, list)):
                found.extend(find_products(value))

    return found


class ProductHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)

        self.text_parts = []
        self.products = []
        self.inside_script = False
        self.inside_style = False
        self.is_json_ld = False
        self.script_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag == "style":
            self.inside_style = True

        if tag == "script":
            self.inside_script = True
            self.is_json_ld = (
                attributes.get("type", "").lower()
                == "application/ld+json"
            )
            self.script_parts = []

    def handle_endtag(self, tag):
        if tag == "style":
            self.inside_style = False

        if tag == "script":
            if self.is_json_ld:
                try:
                    data = json.loads(
                        "".join(self.script_parts)
                    )
                    self.products.extend(
                        find_products(data)
                    )
                except json.JSONDecodeError:
                    pass

            self.inside_script = False
            self.is_json_ld = False
            self.script_parts = []

    def handle_data(self, data):
        if self.inside_script:
            if self.is_json_ld:
                self.script_parts.append(data)
            return

        if self.inside_style:
            return

        text = " ".join(data.split())

        if text:
            self.text_parts.append(text)


def matches(name, required_terms):
    text = normalize(name)

    return all(
        normalize(term) in text
        for term in required_terms
    )


def download_page(url):
    parsed = urlparse(url)

    host = parsed.hostname or ""

    if (
        parsed.scheme != "https"
        or not host.endswith(".md")
        or parsed.username
        or parsed.password
    ):
        raise ValueError(
            "Only approved Moldova HTTPS sources are allowed"
        )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "COSTARO-PriceResearch/0.3",
            "Accept": "text/html",
        },
    )

    with urllib.request.urlopen(
        request,
        timeout=20,
    ) as response:

        final_url = urlparse(response.geturl())

        if (
            final_url.scheme != "https"
            or not (final_url.hostname or "").endswith(".md")
        ):
            raise ValueError("Unexpected redirect")

        content_type = response.headers.get(
            "Content-Type", ""
        ).lower()

        if "text/html" not in content_type:
            raise ValueError("Unexpected content type")

        raw = response.read(2_000_001)

        if len(raw) > 2_000_000:
            raise ValueError("Page too large")

        return raw.decode(
            "utf-8",
            errors="replace",
        )


def extract_price(html, required_terms, product_code):
    parser = ProductHTML()
    parser.feed(html)

    structured_prices = []

    for product in parser.products:
        if not matches(
            product.get("name", ""),
            required_terms,
        ):
            continue

        sku = str(product.get("sku", "")).strip()

        if sku and product_code and sku != product_code:
            continue

        offers = product.get("offers", [])

        if isinstance(offers, dict):
            offers = [offers]

        if not isinstance(offers, list):
            continue

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            currency = offer.get(
                "priceCurrency",
                "MDL",
            )

            if currency != "MDL":
                continue

            price = parse_price(
                offer.get("price", "")
            )

            if price is not None:
                structured_prices.append(price)

    unique = sorted(set(structured_prices))

    if len(unique) == 1:
        return unique[0], "candidate", "structured_data"

    if len(unique) > 1:
        return None, "ambiguous", "structured_data"

    price_pattern = re.compile(
        r"(?<!\d)(\d{1,6}(?:[.,]\d{1,2})?)"
        r"\s*(?:MDL|lei)\b",
        re.IGNORECASE,
    )

    visible_prices = []
    parts = parser.text_parts

    for index, text in enumerate(parts):
        if not matches(text, required_terms):
            continue

        nearby = parts[index + 1:index + 16]

        for fragment in nearby:
            for value in price_pattern.findall(fragment):
                price = parse_price(value)

                if price is not None:
                    visible_prices.append(price)

    unique = sorted(set(visible_prices))

    if len(unique) == 1:
        return unique[0], "candidate", "visible_text"

    if len(unique) > 1:
        return None, "ambiguous", "visible_text"

    return None, "unavailable", "none"


def main():
    with SOURCES.open("r", encoding="utf-8") as file:
        config = json.load(file)

    if config.get("schemaVersion") != 1:
        raise ValueError("Invalid schema version")

    if config.get("country") != "MD":
        raise ValueError("Invalid country")

    if config.get("currency") != "MDL":
        raise ValueError("Invalid currency")

    if config.get("automaticPublicationEnabled") is not False:
        raise ValueError(
            "Automatic publication must remain disabled"
        )

    materials = config.get("materials")

    if not isinstance(materials, list) or not materials:
        raise ValueError("Material sources are missing")

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
                "productCode": source.get(
                    "productCode", ""
                ),
                "price": None,
                "status": "unavailable",
                "extractionMethod": "none",
            }

            terms = source.get(
                "matchTerms",
                material.get("matchTerms"),
            )

            if terms is None:
                terms = [material["name"]]

            if (
                not isinstance(terms, list)
                or not terms
                or not all(
                    isinstance(term, str) and term.strip()
                    for term in terms
                )
            ):
                raise ValueError(
                    "Invalid matchTerms configuration"
                )

            try:
                html = download_page(source["url"])

                price, status, method = extract_price(
                    html,
                    terms,
                    str(source.get("productCode", "")),
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
                f"{observation['price']} MDL"
            )

        candidates = [
            item["price"]
            for item in observations
            if (
                item["status"] == "candidate"
                and item["price"] is not None
            )
        ]

        median = None

        if len(candidates) >= 2:
            minimum = min(candidates)
            maximum = max(candidates)

            if maximum <= minimum * 1.20:
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

    with OUTPUT.open("w", encoding="utf-8") as file:
        json.dump(
            report,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(f"Report saved: {OUTPUT}")
    print("Published prices were NOT changed.")


if __name__ == "__main__":
    main()
