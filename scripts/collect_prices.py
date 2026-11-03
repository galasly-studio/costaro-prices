"""COSTARO: read-only monitoring of Moldova material prices."""

import json
import re
import socket
import ssl
import statistics
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse


SOURCES = Path("price_sources.json")
OUTPUT = Path("price_observations.json")


def error_category(error):
    """Expose a safe failure category, never response HTML or credentials."""
    if isinstance(error, urllib.error.HTTPError):
        return f"http_{error.code}"
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        if isinstance(reason, (TimeoutError, socket.timeout)):
            return "timeout"
        if isinstance(reason, socket.gaierror):
            return "dns_error"
        if isinstance(reason, ssl.SSLError):
            return "tls_error"
        return "network_error"
    if isinstance(error, ValueError):
        return {
            "Unexpected redirect": "unexpected_redirect",
            "Unexpected content type": "unexpected_content_type",
            "Page too large": "response_too_large",
            "Only approved Moldova HTTPS sources are allowed": "invalid_source_url",
        }.get(str(error), "invalid_response")
    if isinstance(error, UnicodeError):
        return "decoding_error"
    return "unknown_error"


def source_health(material_rows):
    """Aggregate source failures for Actions Summary without assuming prices."""
    by_store = defaultdict(lambda: {"total": 0, "candidate": 0,
                                    "unavailable": 0, "ambiguous": 0,
                                    "errors": Counter(), "methods": Counter()})
    for material in material_rows:
        for observation in material.get("observations", []):
            store = observation.get("store") or "Unknown"
            result = by_store[store]
            result["total"] += 1
            status = observation.get("status")
            if status in ("candidate", "unavailable", "ambiguous"):
                result[status] += 1
            else:
                result["unavailable"] += 1
                result["errors"]["invalid_status"] += 1
            if observation.get("error"):
                result["errors"][observation["error"]] += 1
            if status == "candidate":
                result["methods"][observation.get("extractionMethod") or "none"] += 1
    return [{"store": store,
             "total": row["total"], "candidate": row["candidate"],
             "unavailable": row["unavailable"], "ambiguous": row["ambiguous"],
             "errors": dict(sorted(row["errors"].items())),
             "methods": dict(sorted(row["methods"].items()))}
            for store, row in sorted(by_store.items())]


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
        self.headings = []
        self.inside_h1 = False
        self.heading_parts = []
        self.inside_script = False
        self.inside_style = False
        self.is_json_ld = False
        self.script_parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag == "h1":
            self.inside_h1 = True
            self.heading_parts = []

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
        if tag == "h1" and self.inside_h1:
            self.headings.append(" ".join(self.heading_parts).strip())
            self.heading_parts = []
            self.inside_h1 = False

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

        if self.inside_h1:
            self.heading_parts.append(data)

        text = " ".join(data.split())

        if text:
            self.text_parts.append(text)

class PrimaryProductMicrodata(HTMLParser):
    """Read the main product's heading, SKU and price."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside_h1 = False
        self.heading_parts = []
        self.skus = []
        self.prices = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag == "h1":
            self.inside_h1 = True

        if tag != "meta":
            return

        itemprop = attributes.get("itemprop", "").lower()
        content = attributes.get("content", "").strip()

        if itemprop == "sku" and content:
            self.skus.append(content)

        elif itemprop == "price" and content:
            price = parse_price(content)

            if price is not None:
                self.prices.append(price)

    def handle_endtag(self, tag):
        if tag == "h1":
            self.inside_h1 = False

    def handle_data(self, data):
        if self.inside_h1:
            self.heading_parts.append(data)


def extract_primary_microdata_price(html, required_terms, product_code):
    """
    Accept a price only when the main product heading
    and exact SKU match the configured source.
    """
    parser = PrimaryProductMicrodata()
    parser.feed(html)

    heading = " ".join(parser.heading_parts).strip()

    if not matches(heading, required_terms):
        return None

    if not product_code:
        return None

    if product_code not in parser.skus:
        return None

    unique_prices = sorted(set(parser.prices))

    if len(unique_prices) != 1:
        return None

    return unique_prices[0]


class NanuPrimaryProduct(HTMLParser):
    """Read ONLY the visible code and per-piece price in Nanu's main #product."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.inside_heading = False
        self.heading = []
        self.product_depth = 0
        self.active_model = False
        self.active_price = False
        self.active_unit = False
        self.model_parts = []
        self.price_parts = []
        self.unit_parts = []
        self.model_lines = []
        self.price_lines = []
        self.unit_lines = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)

        if tag == "h1":
            self.inside_heading = True

        if tag == "div":
            if self.product_depth:
                self.product_depth += 1
            elif attributes.get("id") == "product":
                self.product_depth = 1

            if self.product_depth:
                classes = set(attributes.get("class", "").split())
                if "price-new" in classes:
                    self.active_price = True
                    self.price_parts = []
                if "for" in classes:
                    self.active_unit = True
                    self.unit_parts = []

        if tag == "p" and self.product_depth:
            if "product-model" in attributes.get("class", "").split():
                self.active_model = True
                self.model_parts = []

    def handle_endtag(self, tag):
        if tag == "h1":
            self.inside_heading = False

        if tag == "p" and self.active_model:
            self.model_lines.append(" ".join(self.model_parts))
            self.active_model = False

        if tag == "div" and self.product_depth:
            if self.active_price:
                self.price_lines.append(" ".join(self.price_parts))
                self.active_price = False
            if self.active_unit:
                self.unit_lines.append(" ".join(self.unit_parts))
                self.active_unit = False
            self.product_depth -= 1

    def handle_data(self, data):
        if self.inside_heading:
            self.heading.append(data)
        if self.active_model:
            self.model_parts.append(data)
        if self.active_price:
            self.price_parts.append(data)
        if self.active_unit:
            self.unit_parts.append(data)


def extract_nanu_per_piece_price(html, required_terms, product_code):
    """Reject recommendations, mismatched SKUs, and whole-pack prices."""
    if not product_code:
        return None

    parser = NanuPrimaryProduct()
    parser.feed(html)

    if not matches(" ".join(parser.heading), required_terms):
        return None

    product_codes = []
    for line in parser.model_lines:
        found = re.fullmatch(r"\s*Cod\s*:\s*(\S+)\s*", line, re.IGNORECASE)
        if found:
            product_codes.append(found.group(1))

    if product_codes != [product_code]:
        return None

    if len(parser.unit_lines) != 1 or "pret per buc" not in normalize(parser.unit_lines[0]):
        return None

    if len(parser.price_lines) != 1:
        return None

    found = re.fullmatch(
        r"\s*(\d{1,6}(?:[.,]\d{1,2})?)\s*(?:mdl|lei)\s*",
        parser.price_lines[0],
        re.IGNORECASE,
    )
    return parse_price(found.group(1)) if found else None


def matches(name, required_terms):
    text = normalize(name)

    return all(
        normalize(term) in text
        for term in required_terms
    )


def same_product_url(candidate, configured):
    """Match the real HTTPS product path, not a recommendation or other host."""
    if not isinstance(candidate, str) or not isinstance(configured, str):
        return False
    try:
        actual, expected = urlparse(candidate), urlparse(configured)
        if (actual.scheme != "https" or expected.scheme != "https"
                or actual.username or actual.password or expected.username
                or expected.password or actual.port or expected.port):
            return False
    except ValueError:
        return False
    return (actual.hostname or "").casefold().removeprefix("www.") == (
        expected.hostname or "").casefold().removeprefix("www.") and (
        actual.path.rstrip("/") or "/") == (
        expected.path.rstrip("/") or "/") and actual.query == expected.query


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


# Stage 28: exact ObraMag main-card research.
# These pinned products stay research-only. A visually scoped price is
# NOT strong structured-SKU evidence for automatic publication.
OBRAMAG_SCOPED_RESEARCH = {
    "/product/glet-finisare-acril-b-62-satroc-8kg": "370035",
    "/product/glet-finisare-acril-satroc-8kg": "6000120",
    "/product/vopsea-interior-supraten-euroton-lav-7kg": "350014",
}


class ObraMagPrimaryCard(HTMLParser):
    """Collect text after the unique H1, excluding scripts and related cards."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.headings = []
        self.parts = []
        self.in_h1 = False
        self.heading_parts = []
        self.after_h1 = False
        self.stopped = False
        self.ignored = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "noscript", "template"):
            self.ignored += 1
            return

        if self.ignored:
            return

        if tag == "h1":
            if self.after_h1:
                self.stopped = True
            self.in_h1 = True
            self.heading_parts = []

        elif self.after_h1 and tag in (
            "h2", "h3", "h4", "aside", "footer"
        ):
            self.stopped = True

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "template"):
            if self.ignored:
                self.ignored -= 1
            return

        if self.ignored:
            return

        if tag == "h1" and self.in_h1:
            self.headings.append(
                " ".join(self.heading_parts).strip()
            )
            self.in_h1 = False
            self.after_h1 = True

    def handle_data(self, data):
        if self.ignored:
            return

        value = " ".join(data.split())
        if not value:
            return

        if self.in_h1:
            self.heading_parts.append(value)
            return

        if self.after_h1 and not self.stopped:
            if value.casefold() in (
                "cantitate",
                "quantity",
                "adaugă în coș",
                "cumpără acum",
            ):
                self.stopped = True
                return

            self.parts.append(value)

            # The main SKU and price should be close to the main heading.
            # Never scan the rest of a long product/recommendation page.
            if len(self.parts) > 100:
                self.stopped = True


def extract_obramag_primary_card_price(
    html, required_terms, product_code
):
    """Research price only when main H1, exact code and MDL/bucket agree."""
    if not isinstance(html, str) or not product_code:
        return None

    parser = ObraMagPrimaryCard()
    parser.feed(html)

    if len(parser.headings) != 1:
        return None

    if not matches(parser.headings[0], required_terms):
        return None

    body = " ".join(parser.parts)

    codes = re.findall(
        r"\bCod(?:\s+produs)?\s*:\s*([a-zA-Z0-9-]+)\b",
        body,
        flags=re.IGNORECASE,
    )

    if codes != [product_code]:
        return None

    prices = re.findall(
        r"\b(?:Pre[țţt]|Price)\s*:?\s*"
        r"(\d{1,6}(?:[.,]\d{1,2})?)"
        r"\s*MDL\s*/\s*cal\b",
        body,
        flags=re.IGNORECASE,
    )

    # Zero prices, two possible prices, or a different unit are unsafe.
    if len(prices) != 1:
        return None

    return parse_price(prices[0])

def extract_price(html, required_terms, product_code, source_url=None):
    # Stage 28: pinned ObraMag pages must pass main-card checks.
    # No fallback to loose page text or related-product recommendations.
    parsed_source = (
        urlparse(source_url)
        if isinstance(source_url, str)
        else None
    )

    if (
        parsed_source
        and parsed_source.hostname in ("obramag.md", "www.obramag.md")
        and parsed_source.path.rstrip("/") in OBRAMAG_SCOPED_RESEARCH
    ):
        expected_code = OBRAMAG_SCOPED_RESEARCH[
            parsed_source.path.rstrip("/")
        ]

        if (
            parsed_source.scheme != "https"
            or parsed_source.username
            or parsed_source.password
            or parsed_source.port
            or parsed_source.query
            or product_code != expected_code
        ):
            return None, "unavailable", "product_scoped_visible_text"

        scoped_price = extract_obramag_primary_card_price(
            html, required_terms, product_code
        )

        if scoped_price is None:
            return None, "unavailable", "product_scoped_visible_text"

        return scoped_price, "candidate", "product_scoped_visible_text"

    # Nanu does not expose the main price as schema.org microdata/JSON-LD.
    # Its price must be pinned to #product + exact "Cod" + "pret per buc".
    # Fail closed: never fall back to a related product's visible price.
    if source_url and urlparse(source_url).hostname in ("nanu.md", "www.nanu.md"):
        price = extract_nanu_per_piece_price(html, required_terms, product_code)
        if price is not None:
            return price, "candidate", "product_scoped_visible_text"
        return None, "unavailable", "product_scoped_visible_text"

    primary_price = extract_primary_microdata_price(
        html,
        required_terms,
        product_code,
    )

    if primary_price is not None:
        return (
            primary_price,
            "candidate",
            "product_microdata",
        )

    parser = ProductHTML()
    parser.feed(html)

    structured_prices = []
    strongly_identified_prices = []
    identity_conflict = False
    main_heading_matches = (
        len(parser.headings) == 1
        and matches(parser.headings[0], required_terms)
    )

    for product in parser.products:
        if not matches(
            product.get("name", ""),
            required_terms,
        ):
            continue

        sku = str(product.get("sku", "")).strip()
        mpn = str(product.get("mpn", "")).strip()

        # Some shops expose the URL's internal ID as schema.org sku,
        # but display their retail product code as schema.org mpn.
        # Accept that exact code without accepting an unrelated SKU/MPN.
        if product_code and (sku or mpn) and product_code not in (sku, mpn):
            identity_conflict = True
            continue

        offers = product.get("offers", [])

        if isinstance(offers, dict):
            offers = [offers]

        if not isinstance(offers, list):
            continue

        for offer in offers:
            if not isinstance(offer, dict):
                continue

            currency = str(offer.get("priceCurrency", "MDL")).strip().upper()

            if currency != "MDL":
                continue

            price = parse_price(
                offer.get("price", "")
            )

            if price is not None:
                structured_prices.append(price)
                # JSON-LD by itself may describe recommended products.
                # Promote evidence ONLY for the unique main product with
                # exact retail code, explicit MDL and canonical product URL.
                identity_urls = [product.get("url"), offer.get("url")]
                identity_urls = [url for url in identity_urls if url is not None]
                strong_identity = (
                    main_heading_matches
                    and bool(product_code)
                    and product_code in (sku, mpn)
                    and currency == "MDL"
                    and str(offer.get("priceCurrency", "")).strip().upper() == "MDL"
                    and bool(identity_urls)
                    and all(same_product_url(url, source_url)
                            for url in identity_urls)
                )
                if strong_identity:
                    strongly_identified_prices.append(price)
                else:
                    identity_conflict = True

    unique = sorted(set(structured_prices))

    if len(unique) == 1:
        if (not identity_conflict and len(strongly_identified_prices) ==
                len(structured_prices) and strongly_identified_prices):
            return unique[0], "candidate", "product_structured_sku"
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
    # A 403/429 is a site-level access/rate-limit refusal, not a reason to
    # request dozens of additional product pages from the same hostname.
    blocked_hosts = {}

    for material in materials:
        observations = []

        for source in material["sources"]:
            host = (urlparse(source["url"]).hostname or "").lower()
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

            if host in blocked_hosts:
                observation["error"] = "skipped_after_" + blocked_hosts[host]
            else:
                try:
                    html = download_page(source["url"])

                    price, status, method = extract_price(
                        html,
                        terms,
                        str(source.get("productCode", "")),
                        source["url"],
                    )

                    observation["price"] = price
                    observation["status"] = status
                    observation["extractionMethod"] = method
                    if status == "ambiguous":
                        observation["error"] = "multiple_possible_prices"
                    elif status != "candidate":
                        observation["error"] = "product_identity_or_price_not_verified"

                except (
                    ValueError,
                    TimeoutError,
                    urllib.error.URLError,
                    UnicodeError,
                ) as error:
                    category = error_category(error)
                    observation["error"] = category
                    if category in ("http_403", "http_429"):
                        blocked_hosts[host] = category

            observations.append(observation)

            print(
                f"{source['store']}: "
                f"{observation['status']} | "
                f"{observation['price']} MDL | "
                f"{observation.get('error', observation['extractionMethod'])}"
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

    report["sourceHealth"] = source_health(report["materials"])
    print("=== COSTARO RETAIL SOURCE HEALTH ===")
    for row in report["sourceHealth"]:
        reasons = ", ".join(f"{kind}:{count}" for kind, count in row["errors"].items())
        print(f"{row['store']}: {row['candidate']}/{row['total']} candidates"
              f" | {reasons or 'no errors'}")

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
