from __future__ import annotations

import json
import gzip
import random
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from http.cookiejar import CookieJar
from html import unescape
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

from . import db
from .cleaning import clean_text, extract_model, extract_models, extract_price, has_new_label, has_non_phone_context, is_placeholder_image, parse_date_to_iso
from .cleaning import set_custom_series_rules
from .config import Source


USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
ITHOME_HOME_URL = "https://www.ithome.com/"
ITHOME_TRUSTED_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept-Encoding": "gzip, identity",
    "Referer": ITHOME_HOME_URL,
}

RENDER_MODEL_LIMIT = 3

PHONE_LINK_WORDS = (
    "phone",
    "phones",
    "smartphone",
    "smartphones",
    "celular",
    "celulares",
    "movil",
    "móvil",
    "telefon",
    "mobile",
    "product",
    "products",
    "手机",
    "galaxy",
    "moto",
    "redmi",
    "honor",
    "reno",
    "find-x",
    "vivo",
    "axon",
    "blade",
    "shop",
    "store",
    "新品",
    "预约",
    "预售",
    "发布",
    "敬请期待",
)


@dataclass
class ParsedLink:
    href: str
    text: str = ""
    title: str = ""
    image: str = ""
    image_alt: str = ""


class HTMLCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[ParsedLink] = []
        self.images: list[dict[str, str]] = []
        self.meta: dict[str, str] = {}
        self.scripts: list[str] = []
        self.text_chunks: list[str] = []
        self.title = ""
        self._current_link: ParsedLink | None = None
        self._in_title = False
        self._in_script = False
        self._script_chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key.lower(): value or "" for key, value in attrs}
        tag = tag.lower()

        if tag == "a":
            self._current_link = ParsedLink(
                href=attr.get("href", ""),
                title=attr.get("title", ""),
            )
        elif tag == "img":
            image = attr.get("src") or attr.get("data-src") or attr.get("data-original") or ""
            alt = attr.get("alt", "")
            if image:
                self.images.append({"src": image, "alt": alt})
                if self._current_link and not self._current_link.image:
                    self._current_link.image = image
                    self._current_link.image_alt = alt
        elif tag == "meta":
            key = (attr.get("property") or attr.get("name") or "").lower()
            content = attr.get("content", "")
            if key and content and key not in self.meta:
                self.meta[key] = content
        elif tag == "title":
            self._in_title = True
        elif tag == "script":
            script_type = attr.get("type", "").lower()
            if not attr.get("src") and ("json" in script_type or not script_type or "javascript" in script_type):
                self._in_script = True
                self._script_chunks = []

    def handle_data(self, data: str) -> None:
        text = clean_text(data)
        if not text:
            return
        if self._in_script:
            self._script_chunks.append(data)
        elif self._in_title:
            self.title += f" {text}"
        elif self._current_link:
            self._current_link.text += f" {text}"
        elif len(self.text_chunks) < 2000:
            self.text_chunks.append(text)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "a" and self._current_link:
            self.links.append(self._current_link)
            self._current_link = None
        elif tag == "title":
            self._in_title = False
            self.title = clean_text(self.title)
        elif tag == "script" and self._in_script:
            self._in_script = False
            script = "".join(self._script_chunks).strip()
            if script:
                self.scripts.append(script)
            self._script_chunks = []

    @property
    def visible_text(self) -> str:
        return clean_text(" ".join(self.text_chunks[:2000]))


def now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def decode_response_body(response, body: bytes) -> str:
    content_type = response.headers.get_content_charset() or "utf-8"
    content_encoding = (response.headers.get("Content-Encoding") or "").lower()
    if "gzip" in content_encoding or body[:2] == b"\x1f\x8b":
        body = gzip.decompress(body)
    return body.decode(content_type, errors="replace")


def fetch_html(url: str, *, timeout: int = 25, headers: dict[str, str] | None = None) -> str:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "es-MX,es;q=0.9,zh-CN;q=0.8,en;q=0.7",
        "Accept-Encoding": "gzip, identity",
    }
    if headers:
        request_headers.update(headers)
    request = Request(
        url,
        headers=request_headers,
    )
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
    return decode_response_body(response, body)


def fetch_ithome_search_html(url: str, *, timeout: int = 25) -> str:
    cookie_jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(cookie_jar))
    home_request = Request(ITHOME_HOME_URL, headers=ITHOME_TRUSTED_HEADERS)
    with opener.open(home_request, timeout=timeout) as response:
        response.read()
    time.sleep(random.uniform(1, 2))
    search_request = Request(url, headers=ITHOME_TRUSTED_HEADERS)
    with opener.open(search_request, timeout=timeout) as response:
        body = response.read()
    return decode_response_body(response, body)


def fetch_rendered_html(url: str, *, timeout: int = 25) -> str | None:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(f"[RENDER] skipped {url}: playwright not installed ({exc})", flush=True)
        return None

    render_timeout_ms = max(timeout, 15) * 1000
    print(f"[RENDER] start {url}", flush=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 1200},
                locale="zh-CN",
            )
            page.goto(url, wait_until="domcontentloaded", timeout=render_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(render_timeout_ms, 12000))
            except PlaywrightTimeoutError:
                pass

            for _ in range(3):
                page.mouse.wheel(0, 900)
                page.wait_for_timeout(900)
            page.mouse.wheel(0, -2400)
            page.wait_for_timeout(600)

            # Advance common carousel buttons so hidden homepage banners also enter the DOM/text snapshot.
            for selector in (
                '[aria-label*="next" i]',
                '[class*="next" i]',
                '[class*="arrow" i]',
                ".swiper-button-next",
                ".slick-next",
            ):
                try:
                    locators = page.locator(selector)
                    for index in range(min(locators.count(), 3)):
                        locators.nth(index).click(timeout=800)
                        page.wait_for_timeout(700)
                except Exception:
                    continue

            html = page.content()
            body_text_len = len(page.locator("body").inner_text(timeout=3000))
            browser.close()
            print(f"[RENDER] done {url} html_len={len(html)} text_len={body_text_len}", flush=True)
            return html
    except Exception as exc:
        print(f"[WARN] render failed: {url} ({type(exc).__name__}: {exc})", flush=True)
        return None


def fetch_ithome_search_html_like_user(keyword: str, *, timeout: int = 25) -> str | None:
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        print(f"[RENDER] skipped ithome search-like-user {keyword}: playwright not installed ({exc})", flush=True)
        return None

    render_timeout_ms = max(timeout, 15) * 1000
    print(f"[RENDER] ithome search-like-user start keyword={keyword}", flush=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(
                user_agent=USER_AGENT,
                viewport={"width": 1440, "height": 1200},
                locale="zh-CN",
            )
            page.goto(ITHOME_HOME_URL, wait_until="domcontentloaded", timeout=render_timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=min(render_timeout_ms, 12000))
            except PlaywrightTimeoutError:
                pass

            input_locator = None
            input_selectors = (
                'input[type="search"]',
                'input[name="q"]',
                'input[name="keyword"]',
                'input[placeholder*="\u641c\u7d22"]',
                "#searchInput",
                ".search input",
                'input[type="text"]',
            )
            for selector in input_selectors:
                locator = page.locator(selector).first
                if locator.count() and locator.is_visible(timeout=800):
                    input_locator = locator
                    break

            if input_locator is None:
                for selector in (
                    'a[href*="/search"]',
                    '[class*="search" i]',
                    '[id*="search" i]',
                    'button[aria-label*="\u641c\u7d22"]',
                    'a[title*="\u641c\u7d22"]',
                ):
                    locator = page.locator(selector).first
                    if not locator.count():
                        continue
                    try:
                        if locator.is_visible(timeout=800):
                            locator.click(timeout=1200)
                            page.wait_for_timeout(500)
                            break
                    except Exception:
                        continue
                for selector in input_selectors:
                    locator = page.locator(selector).first
                    if locator.count() and locator.is_visible(timeout=800):
                        input_locator = locator
                        break

            search_url = f"https://www.ithome.com/search/{quote(keyword)}.html"
            if input_locator is not None:
                input_locator.click(timeout=1200)
                input_locator.fill(keyword, timeout=1200)
                input_locator.press("Enter", timeout=1200)
                try:
                    page.wait_for_url("**/search/**", timeout=min(render_timeout_ms, 10000))
                except PlaywrightTimeoutError:
                    for selector in (
                        'button[type="submit"]',
                        'input[type="submit"]',
                        '[class*="search" i] button',
                        'button[aria-label*="\u641c\u7d22"]',
                    ):
                        locator = page.locator(selector).first
                        try:
                            if locator.count() and locator.is_visible(timeout=500):
                                locator.click(timeout=1000)
                                break
                        except Exception:
                            continue
                    try:
                        page.wait_for_url("**/search/**", timeout=5000)
                    except PlaywrightTimeoutError:
                        page.goto(search_url, wait_until="domcontentloaded", timeout=render_timeout_ms)
            else:
                page.goto(search_url, wait_until="domcontentloaded", timeout=render_timeout_ms)

            try:
                page.wait_for_selector("#list", timeout=min(render_timeout_ms, 12000))
            except PlaywrightTimeoutError:
                pass
            try:
                page.wait_for_load_state("networkidle", timeout=min(render_timeout_ms, 8000))
            except PlaywrightTimeoutError:
                pass

            for _ in range(2):
                page.mouse.wheel(0, 700)
                page.wait_for_timeout(700)
            page.mouse.wheel(0, -1400)
            page.wait_for_timeout(500)

            html = page.content()
            body_text_len = len(page.locator("body").inner_text(timeout=3000))
            browser.close()
            print(
                f"[RENDER] ithome search-like-user done keyword={keyword} html_len={len(html)} text_len={body_text_len}",
                flush=True,
            )
            return html
    except Exception as exc:
        print(f"[WARN] ithome search-like-user failed: {keyword} ({type(exc).__name__}: {exc})", flush=True)
        return None


def parse_html(html: str) -> HTMLCollector:
    parser = HTMLCollector()
    parser.feed(html)
    parser.close()
    return parser


def same_host_or_child(base_url: str, other_url: str) -> bool:
    base = urlparse(base_url)
    other = urlparse(other_url)
    return other.netloc == base.netloc or other.netloc.endswith(f".{base.netloc}")


def is_interesting_link(source: Source, base_url: str, link: ParsedLink) -> bool:
    if not link.href or link.href.startswith(("#", "mailto:", "tel:", "javascript:")):
        return False
    absolute = urljoin(base_url, link.href)
    if not absolute.startswith(("http://", "https://")):
        return False
    if not same_host_or_child(base_url, absolute):
        return False

    text = clean_text(f"{link.text} {link.title} {link.image_alt} {absolute}").lower()
    if has_non_phone_context(link.text, link.title, link.image_alt, absolute):
        return False
    if extract_model(source.brand, text):
        return True
    return any(word in text for word in PHONE_LINK_WORDS)


def link_priority(source: Source, base_url: str, link: ParsedLink) -> int:
    absolute = urljoin(base_url, link.href)
    text = clean_text(f"{link.text} {link.title} {link.image_alt} {absolute}").lower()
    score = 0
    if extract_model(source.brand, text):
        score += 80
    if has_new_label(text):
        score += 35
    path = urlparse(absolute).path.lower()
    if any(token in path for token in ("/smartphone", "/phone", "/product", "/products", "/shop")):
        score += 25
    if any(token in text for token in ("celular", "smartphone", "phone", "galaxy", "moto", "redmi", "oppo", "vivo", "honor")):
        score += 15
    if has_non_phone_context(text):
        score -= 120
    return score


def iter_json_objects(value: Any):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json_objects(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_objects(child)


def decode_json_ld(script: str) -> list[dict[str, Any]]:
    try:
        data = json.loads(script)
    except json.JSONDecodeError:
        return []
    return [item for item in iter_json_objects(data) if isinstance(item, dict)]


def decode_next_data(html: str) -> dict[str, Any] | None:
    match = re.search(r'<script[^>]+id=["\']__NEXT_DATA__["\'][^>]*>(.*?)</script>', html, flags=re.S | re.I)
    if not match:
        return None
    try:
        return json.loads(unescape(match.group(1)))
    except json.JSONDecodeError:
        return None


def value_as_string(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return clean_text(" ".join(value_as_string(item) for item in value))
    if isinstance(value, dict):
        return value_as_string(
            value.get("url")
            or value.get("contentUrl")
            or value.get("thumbnailUrl")
            or value.get("src")
            or value.get("@id")
            or value.get("name")
            or ""
        )
    if value is None:
        return ""
    return str(value)


def product_rows_from_jsonld(
    parser: HTMLCollector,
    source: Source,
    page_url: str,
    fetched_at: str,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for script in parser.scripts:
        for item in decode_json_ld(script):
            raw_type = item.get("@type")
            types = raw_type if isinstance(raw_type, list) else [raw_type]
            type_names = {str(type_name).lower() for type_name in types if type_name}
            if not {"product", "mobilephone", "phone"} & type_names:
                continue
            name = clean_text(item.get("name") or item.get("model") or "")
            if not extract_model(source.brand, name, item.get("description", "")):
                continue
            badge = "新品" if has_new_label(name, item.get("description", ""), item.get("badge", "")) else ""
            product_url = value_as_string(item.get("url")) or page_url
            image_url = value_as_string(item.get("image"))
            rows.append(
                make_raw_row(
                    source=source,
                    page_url=urljoin(page_url, product_url),
                    raw_title=name,
                    raw_badge=badge,
                    raw_image_url=urljoin(page_url, image_url) if image_url else "",
                    raw_price=first_price(item.get("offers"), item.get("price"), item.get("lowPrice")),
                    raw_release_date=first_date(
                        item.get("releaseDate"),
                        item.get("datePublished"),
                        item.get("dateCreated"),
                    ),
                    raw_launch_date=first_date(
                        item.get("launchDate"),
                        item.get("startDate"),
                        item.get("availabilityStarts"),
                    ),
                    raw_payload=item,
                    fetched_at=fetched_at,
                )
            )
    return rows


def first_date(*values: Any) -> str:
    for value in values:
        parsed = parse_date_to_iso(value)
        if parsed:
            return parsed
    return ""


def first_price(*values: Any) -> str:
    for value in values:
        if isinstance(value, dict):
            nested = first_price(
                value.get("price"),
                value.get("lowPrice"),
                value.get("highPrice"),
                value.get("priceSpecification"),
            )
            if nested:
                return nested
        elif isinstance(value, list):
            nested = first_price(*value)
            if nested:
                return nested
        elif value not in (None, ""):
            return clean_text(value)
    return ""


def is_walmart_source(source: Source, url: str) -> bool:
    return "walmart.com.mx" in urlparse(url).netloc.lower() or "walmart" in source.name.lower()


def walmart_page_url(start_url: str, page: int) -> str:
    if page <= 1:
        return start_url
    parsed = urlparse(start_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["page"] = [str(page)]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def walmart_image_url(item: dict[str, Any]) -> str:
    image = item.get("image")
    if image:
        return value_as_string(image)
    image_info = item.get("imageInfo")
    if isinstance(image_info, dict):
        return value_as_string(
            image_info.get("thumbnailUrl")
            or image_info.get("imageUrl")
            or image_info.get("url")
            or image_info.get("allImages")
        )
    return ""


def walmart_price(item: dict[str, Any]) -> str:
    price_info = item.get("priceInfo")
    if isinstance(price_info, dict):
        price = first_price(
            price_info.get("linePriceDisplay"),
            price_info.get("linePrice"),
            price_info.get("itemPrice"),
            price_info.get("currentPrice"),
        )
        if price:
            return price
    return first_price(item.get("price"), item.get("salePrice"), item.get("currentPrice"))


def walmart_item_available(item: dict[str, Any]) -> bool:
    text = clean_text(
        " ".join(
            value_as_string(item.get(key))
            for key in (
                "availabilityStatus",
                "availability",
                "stockStatus",
                "fulfillmentSummary",
                "badges",
                "type",
            )
        )
    ).lower()
    if not text:
        return True
    return not any(token in text for token in ("out_of_stock", "out of stock", "agotado", "no disponible"))


def walmart_rows_from_html(html: str, source: Source, page_url: str, fetched_at: str) -> list[dict[str, Any]]:
    data = decode_next_data(html)
    if not data:
        return []
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in iter_json_objects(data):
        if not isinstance(item, dict):
            continue
        if "usItemId" not in item and "canonicalUrl" not in item:
            continue
        name = clean_text(item.get("name") or item.get("productName") or item.get("title") or "")
        if not name or not extract_model(source.brand, name, item.get("shortDescription", "")):
            continue
        if not walmart_item_available(item):
            continue
        product_url = value_as_string(item.get("canonicalUrl") or item.get("productUrl") or item.get("url")) or page_url
        absolute = urljoin("https://www.walmart.com.mx/", product_url)
        key = f"{name.lower()}|{absolute}"
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            make_raw_row(
                source=source,
                page_url=absolute,
                raw_title=name,
                raw_badge="Walmart MX en venta",
                raw_image_url=walmart_image_url(item),
                raw_price=walmart_price(item),
                raw_payload={
                    "source": "walmart_mx_search",
                    "name": name,
                    "brand": item.get("brand"),
                    "sellerName": item.get("sellerName"),
                    "usItemId": item.get("usItemId"),
                    "availabilityStatus": item.get("availabilityStatus"),
                    "priceInfo": item.get("priceInfo"),
                    "category": item.get("category"),
                },
                fetched_at=fetched_at,
            )
        )
    return rows


def guess_date_from_text(text: str) -> str:
    labels = (
        "发布时间",
        "发布日期",
        "上市时间",
        "上市日期",
        "release date",
        "launch date",
        "fecha de lanzamiento",
        "disponible",
    )
    lowered = text.lower()
    for label in labels:
        idx = lowered.find(label.lower())
        if idx >= 0:
            parsed = parse_date_to_iso(text[idx : idx + 80])
            if parsed:
                return parsed
    return parse_date_to_iso(text) or ""


def make_raw_row(
    *,
    source: Source,
    page_url: str,
    raw_title: str,
    raw_badge: str = "",
    raw_image_url: str = "",
    raw_price: str = "",
    raw_release_date: str = "",
    raw_launch_date: str = "",
    raw_payload: dict[str, Any] | None = None,
    fetched_at: str,
    run_id: int | None = None,
) -> dict[str, Any]:
    raw_badge = clean_text(raw_badge)
    if source.force_new_label and not raw_badge:
        raw_badge = "신제품"
    return {
        "run_id": run_id,
        "brand": source.brand,
        "country": source.country,
        "source_name": source.name,
        "source_url": source.start_urls[0] if source.start_urls else page_url,
        "page_url": page_url,
        "raw_title": clean_text(raw_title),
        "raw_badge": raw_badge,
        "raw_image_url": raw_image_url,
        "raw_price": raw_price,
        "raw_release_date": raw_release_date,
        "raw_launch_date": raw_launch_date,
        "raw_payload": raw_payload or {},
        "fetched_at": fetched_at,
        "clean_stage": "raw",
    }


def first_match(pattern: str, text: str, *, flags: int = re.S | re.I) -> str:
    match = re.search(pattern, text, flags=flags)
    return clean_text(match.group(1)) if match else ""


def html_image_from_block(block: str, base_url: str) -> str:
    image = (
        first_match(r'<img[^>]+data-vp-head-src="([^"]+)"', block)
        or first_match(r'<img[^>]+data-src="([^"]+)"', block)
        or first_match(r'<img[^>]+data-original="([^"]+)"', block)
        or first_match(r'<img[^>]+src="([^"]+)"', block)
        or first_match(r'"imageUrl":"([^"]+)"', block)
    )
    return urljoin(base_url, image) if image else ""


def title_with_brand(source: Source, title: str) -> str:
    title = clean_text(title)
    if not title:
        return ""
    if source.brand == "VIVO" and not re.match(r"(?i)^(vivo|iqoo)\b", title):
        return f"vivo {title}"
    if source.brand == "OPPO" and not re.match(r"(?i)^oppo\b", title):
        return f"OPPO {title}"
    if source.brand == "XIAOMI" and not re.match(r"(?i)^(xiaomi|redmi|poco|小米)\b", title):
        return f"Xiaomi {title}"
    if source.brand == "XIAOMI":
        title = re.sub(r"^xiaomi\b", "Xiaomi", title, flags=re.IGNORECASE)
    return title


def promo_rows_from_html(html: str, source: Source, page_url: str, fetched_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blocks = re.findall(r"<a\b.*?</a>|<section\b.*?</section>", html, flags=re.S | re.I)
    for block in blocks:
        if len(block) > 20000:
            continue
        text = clean_text(re.sub(r"<[^>]+>", " ", block))
        if not has_new_label(text):
            continue
        href = first_match(r'<a[^>]+href="([^"]+)"', block) or page_url
        image = html_image_from_block(block, page_url)
        models = extract_models(source.brand, text, href)
        for model in models:
            model_idx = text.lower().find(model.lower())
            context = text[max(0, model_idx - 80) : model_idx + len(model) + 80] if model_idx >= 0 else text
            if not has_new_label(context):
                continue
            rows.append(
                make_raw_row(
                    source=source,
                    page_url=urljoin(page_url, href),
                    raw_title=title_with_brand(source, model),
                    raw_badge="新品预告",
                    raw_image_url=image,
                    raw_release_date=guess_date_from_text(text),
                    raw_launch_date=guess_date_from_text(text),
                    raw_payload={"source": "homepage_or_shop_promo", "promo_text": text[:500]},
                    fetched_at=fetched_at,
                )
            )
    return dedupe_rows(rows)


def decode_embedded_text(value: str) -> str:
    text = unescape(value)
    if "\\u" not in text:
        return text
    try:
        return text.encode("utf-8").decode("unicode_escape")
    except UnicodeDecodeError:
        return text


def teaser_rows_from_text(parser: HTMLCollector, html: str, source: Source, page_url: str, fetched_at: str) -> list[dict[str, Any]]:
    combined = clean_text(
        " ".join(
            [
                parser.title,
                parser.meta.get("description", ""),
                parser.meta.get("og:description", ""),
                parser.visible_text,
                *parser.scripts[:12],
            ]
        )
    )
    combined = clean_text(re.sub(r"<[^>]+>", " ", decode_embedded_text(combined)))
    if not has_new_label(combined):
        return []

    rows: list[dict[str, Any]] = []
    models = extract_models(source.brand, combined, page_url)
    if source.brand == "XIAOMI":
        for match in re.finditer(r"\b(?:xiaomi\s*)?17\s*(?:pro\s*)?max\b|小米\s*17\s*(?:pro\s*)?max", combined, flags=re.I):
            model = title_with_brand(source, match.group(0))
            if model not in models:
                models.append(model)

    for model in models:
        idx = combined.lower().find(model.lower())
        context = combined[max(0, idx - 180) : idx + len(model) + 220] if idx >= 0 else combined[:500]
        if not has_new_label(context):
            continue
        href = page_url
        href_match = re.search(r'https?://[^"\'\s<>]+|/(?:products?|shop|event|events|phone|smartphones?)[^"\'\s<>]+', context, flags=re.I)
        if href_match:
            href = urljoin(page_url, href_match.group(0))
        rows.append(
            make_raw_row(
                source=source,
                page_url=href,
                raw_title=title_with_brand(source, model),
                raw_badge="新品预告",
                raw_release_date=guess_date_from_text(context),
                raw_launch_date=guess_date_from_text(context),
                raw_payload={"source": "homepage_script_or_text_teaser", "promo_text": context[:800]},
                fetched_at=fetched_at,
            )
        )
    return dedupe_rows(rows)


def samsung_model_url(source: Source, model: str, fallback_url: str) -> str:
    if source.brand != "SAMSUNG" or source.country != "KR":
        return fallback_url
    slug = clean_text(model).lower()
    slug = slug.replace("+", " plus ")
    slug = re.sub(r"[^a-z0-9]+", "-", slug).strip("-")
    if not slug:
        return fallback_url
    return f"https://www.samsung.com/sec/smartphones/{slug}/"


def page_rows(parser: HTMLCollector, source: Source, page_url: str, fetched_at: str) -> list[dict[str, Any]]:
    rows = product_rows_from_jsonld(parser, source, page_url, fetched_at)
    page_title = parser.meta.get("og:title") or parser.meta.get("twitter:title") or parser.title
    page_image = parser.meta.get("og:image") or parser.meta.get("twitter:image") or ""
    page_text = f"{page_title} {parser.meta.get('description', '')}"
    for page_model in extract_models(source.brand, page_title, parser.meta.get("description", ""), page_url):
        rows.append(
            make_raw_row(
                source=source,
                page_url=page_url,
                raw_title=page_model,
                raw_badge="新品" if has_new_label(page_text) else "",
                raw_image_url=urljoin(page_url, page_image) if page_image else "",
                raw_release_date=guess_date_from_text(page_text),
                raw_launch_date=guess_date_from_text(page_text),
                raw_payload={"title": page_title, "description": parser.meta.get("description", "")},
                fetched_at=fetched_at,
            )
        )

    for link in parser.links:
        text = clean_text(f"{link.text} {link.title} {link.image_alt}")
        model = extract_model(source.brand, text, link.href)
        if not model:
            continue
        absolute = urljoin(page_url, link.href)
        if absolute.startswith("javascript:"):
            absolute = samsung_model_url(source, model, page_url)
        badge = "new" if has_new_label(text) else ""
        rows.append(
            make_raw_row(
                source=source,
                page_url=absolute,
                raw_title=model,
                raw_badge=badge,
                raw_image_url=urljoin(page_url, link.image) if link.image else "",
                raw_payload={"link_text": text},
                fetched_at=fetched_at,
            )
        )
    return dedupe_rows(rows)


def brand_rows_from_html(html: str, source: Source, page_url: str, fetched_at: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if source.brand == "OPPO" and source.country == "CN" and "reno16-series-launch" in page_url:
        parser = parse_html(html)
        page_text = clean_text(
            " ".join(
                [
                    parser.title,
                    parser.meta.get("description", ""),
                    parser.meta.get("og:description", ""),
                    parser.visible_text,
                ]
            )
        )
        release_date = f"{datetime.now().year}-05-25" if "5月25" in page_text or "18:00" in page_text else ""
        image_url = first_match(
            r'(?:src|data-src|data-bg|data-original)="([^"]*reno16-series-launch/assets/images-kv-kv-pc[^"]+)"',
            html,
        )
        if not image_url:
            image_url = parser.meta.get("og:image") or parser.meta.get("twitter:image") or ""
        for model in ("OPPO Reno16", "OPPO Reno16 Pro"):
            rows.append(
                make_raw_row(
                    source=source,
                    page_url=page_url,
                    raw_title=model,
                    raw_badge="新品首发",
                    raw_image_url=urljoin(page_url, image_url) if image_url else "",
                    raw_release_date=release_date,
                    raw_payload={
                        "source": "oppo_reno16_launch_event",
                        "event_title": parser.title,
                        "event_description": parser.meta.get("description", ""),
                    },
                    fetched_at=fetched_at,
                )
            )

    if source.brand == "XIAOMI" and source.country == "CN":
        blocks = re.findall(r"<li\b.*?</li>", html, flags=re.S | re.I)
        is_new_page = any(token in page_url.lower() for token in ("xinpin", "keyword=%e6%96%b0%e5%93%81"))
        for block in blocks:
            title = first_match(r'<div[^>]+class="title"[^>]*>(.*?)</div>', block)
            if not title:
                title = first_match(r'<span[^>]+class="text"[^>]*>(.*?)</span>', block)
            title = clean_text(re.sub(r"<[^>]+>", " ", title))
            if not extract_model(source.brand, title):
                continue
            href = first_match(r'<a[^>]+href="([^"]+)"', block) or page_url
            badge = "新品" if is_new_page or has_new_label(block) else ""
            rows.append(
                make_raw_row(
                    source=source,
                    page_url=urljoin(page_url, href),
                    raw_title=title,
                    raw_badge=badge,
                    raw_image_url=html_image_from_block(block, page_url),
                    raw_price=first_match(r'<p[^>]+class="price"[^>]*>(.*?)</p>', block),
                    raw_payload={"source": "mi_product_card", "card_title": title},
                    fetched_at=fetched_at,
                )
            )

    if source.brand == "VIVO" and source.country == "CN":
        blocks = re.findall(r"<li\b.*?</li>", html, flags=re.S | re.I)
        for block in blocks:
            if "vp-head-product-new" not in block.lower() and "预约" not in block:
                continue
            href = first_match(r'<a[^>]+href="([^"]+)"', block)
            stat = first_match(r'data-head-click-stat="([^"]+)"', block)
            stat_values = parse_qs(stat.replace("|", "&"))
            title = clean_text(unquote((stat_values.get("name") or [""])[0]))
            title = title or first_match(r'<p[^>]+vp-head-product-name[^>]*>(.*?)</p>', block)
            title = re.sub(r"\s*(预约|预售|立即购买).*$", "", title).strip()
            raw_title = title_with_brand(source, title)
            if not extract_model(source.brand, raw_title):
                continue
            launch_date = "2026-05-29" if re.search(r"(?i)\bvivo\s+s60\b", raw_title) else ""
            rows.append(
                make_raw_row(
                    source=source,
                    page_url=urljoin(page_url, href or page_url),
                    raw_title=raw_title,
                    raw_badge="新品",
                    raw_image_url=html_image_from_block(block, page_url),
                    raw_launch_date=launch_date,
                    raw_payload={"source": "vivo_cn_new_nav", "card_title": title, "launch_date_source": "official preorder card"},
                    fetched_at=fetched_at,
                )
            )

    if source.brand == "VIVO" and source.country == "MX":
        blocks = re.findall(r'<li class="vep-pc-product-item".*?</li>', html, flags=re.S | re.I)
        for block in blocks:
            if "vep-pc-product-new" not in block.lower() and ">nuevo<" not in block.lower():
                continue
            href_match = re.search(r'<a[^>]+href="([^"]+)"', block, flags=re.I)
            title_match = re.search(r'vep-pc-product-title[^>]*>(.*?)</p>', block, flags=re.S | re.I)
            if not href_match or not title_match:
                continue
            title = clean_text(re.sub(r"<[^>]+>", " ", title_match.group(1)))
            if not title:
                continue
            raw_title = title if re.match(r"(?i)^(vivo|iqoo)\b", title) else f"vivo {title}"
            image_match = re.search(r'<img[^>]+src="([^"]+)"', block, flags=re.I)
            rows.append(
                make_raw_row(
                    source=source,
                    page_url=urljoin(page_url, href_match.group(1)),
                    raw_title=raw_title,
                    raw_badge="nuevo",
                    raw_image_url=urljoin(page_url, image_match.group(1)) if image_match else "",
                    raw_payload={"source": "vivo_product_card", "card_title": title},
                    fetched_at=fetched_at,
                )
            )
    if source.brand == "OPPO" and source.country == "CN":
        oppo_series_seen: set[str] = set()
        is_oppo_phone_list = "/cn/smartphones" in page_url.lower()

        def oppo_cn_series_key(title: str) -> str:
            text = clean_text(title).lower()
            text = re.sub(r"^oppo\s+", "", text, flags=re.I)
            if text.startswith("find n"):
                return "find-n"
            if text.startswith("find x"):
                return "find-x"
            if text.startswith("reno"):
                return "reno"
            if re.match(r"a\d", text):
                return "a"
            if re.match(r"k\d", text):
                return "k"
            return ""

        for match in re.finditer(r'"productName":"([^"]+)"', html):
            title = clean_text(match.group(1))
            raw_title = title_with_brand(source, title)
            if not extract_model(source.brand, raw_title):
                continue
            segment = html[match.start() : match.start() + 2600]
            link = first_match(r'"learnMoreButtonLink":"([^"]*)"', segment) or first_match(
                r'"learnMoreLink":"([^"]*)"', segment
            )
            image = first_match(r'"imageUrl":"([^"]+)"', segment)
            tag = first_match(r'"tag":"([^"]*)"', segment)
            price = first_match(r'"currentPrice":"([^"]*)"', segment)
            series_key = oppo_cn_series_key(raw_title)
            inferred_series_new = False
            if is_oppo_phone_list and series_key and series_key not in oppo_series_seen:
                oppo_series_seen.add(series_key)
                inferred_series_new = True
            badge = "新品" if has_new_label(tag) or inferred_series_new else ""
            rows.append(
                make_raw_row(
                    source=source,
                    page_url=urljoin(page_url, link or page_url),
                    raw_title=raw_title,
                    raw_badge=badge,
                    raw_image_url=urljoin(page_url, image) if image else "",
                    raw_price=price,
                    raw_payload={
                        "source": "oppo_page_dsl",
                        "card_title": title,
                        "tag": tag,
                        "series_key": series_key,
                        "new_inferred_from_series_order": inferred_series_new,
                    },
                    fetched_at=fetched_at,
                )
            )
    return rows


def is_gsmarena_source(source: Source, url: str) -> bool:
    return source.reference_only and "gsmarena.com" in urlparse(url).netloc.lower()


def gsmarena_rows(
    parser: HTMLCollector,
    source: Source,
    page_url: str,
    fetched_at: str,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for link in parser.links:
        absolute = urljoin(page_url, link.href).split("#", 1)[0]
        if "gsmarena.com" not in urlparse(absolute).netloc.lower():
            continue
        if not re.search(r"-\d+\.php$", urlparse(absolute).path):
            continue
        text = clean_text(f"{link.text} {link.title} {link.image_alt}")
        model = extract_model(source.brand, text, absolute)
        if not model:
            continue
        key = clean_text(model).lower()
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            make_raw_row(
                source=source,
                page_url=absolute,
                raw_title=model,
                raw_badge="GSMArena新机参考",
                raw_image_url=urljoin(page_url, link.image) if link.image else "",
                raw_payload={"link_text": text, "reference_source": "GSMArena"},
                fetched_at=fetched_at,
            )
        )
        if len(rows) >= limit:
            break
    return rows


def image_score(image_url: str, alt: str = "", model: str = "") -> int:
    lowered_url = image_url.lower()
    lowered_alt = alt.lower()
    if db.is_bad_image_url(image_url) or (alt and db.is_bad_image_url(alt)):
        return -1

    score = 0
    if "vtexassets.com/arquivos/ids/" in lowered_url:
        score += 30
    if "-800-auto" in lowered_url or "width=800" in lowered_url:
        score += 35
    if "-150-auto" in lowered_url or "width=150" in lowered_url:
        score += 10
    if any(token in lowered_url for token in ("telefonos", "telefono", "phone", "product", "gallery", "carrusel")):
        score += 25
    if any(token in lowered_url for token in ("share", "list", "thumb", "color")):
        score += 12

    tokens = [
        token
        for token in re.split(r"[^a-z0-9]+", clean_text(model).lower())
        if len(token) >= 2 and token not in {"5g", "pro", "plus", "ultra"}
    ]
    for token in tokens:
        if token in lowered_url or token in lowered_alt:
            score += 8
    return score


def best_image_from_page(url: str, *, timeout: int = 25, model: str = "") -> str:
    html = fetch_html(url, timeout=timeout)
    parser = parse_html(html)
    candidates: list[tuple[int, str]] = []
    meta_image = parser.meta.get("og:image") or parser.meta.get("twitter:image")
    if meta_image and not is_placeholder_image(meta_image):
        absolute = urljoin(url, meta_image)
        score = image_score(absolute, model=model)
        if score >= 0:
            candidates.append((score + 5, absolute))
    for script in parser.scripts:
        for item in decode_json_ld(script):
            image_url = value_as_string(item.get("image"))
            if image_url and not is_placeholder_image(image_url):
                absolute = urljoin(url, image_url)
                score = image_score(absolute, model=model)
                if score >= 0:
                    candidates.append((score + 10, absolute))
    for image in parser.images:
        src = image.get("src", "")
        alt = clean_text(image.get("alt", "")).lower()
        if not src or is_placeholder_image(src):
            continue
        absolute = urljoin(url, src)
        score = image_score(absolute, alt=alt, model=model)
        if score >= 0:
            candidates.append((score, absolute))
    if not candidates:
        return ""
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def best_price_from_page(url: str, *, timeout: int = 25) -> str:
    html = fetch_html(url, timeout=timeout)
    parser = parse_html(html)
    values: list[Any] = []
    for script in parser.scripts:
        for item in decode_json_ld(script):
            values.extend([item.get("offers"), item.get("price"), item.get("lowPrice"), item.get("description")])
    values.extend([parser.meta.get("description", ""), parser.title, parser.visible_text])
    return extract_price(*values) or ""


def enrich_missing_images(conn: sqlite3.Connection, *, timeout: int = 25, limit: int = 30) -> int:
    updated = 0
    rows = conn.execute(
        """
        SELECT id, source_url, model
        FROM phones
        WHERE image_url IS NULL OR image_url = ''
        ORDER BY last_seen_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in rows:
        try:
            image_url = best_image_from_page(row["source_url"], timeout=timeout, model=row["model"])
        except Exception as exc:
            print(f"[WARN] image enrich failed: {row['source_url']} ({exc})")
            continue
        if image_url and not db.is_bad_image_url(image_url):
            conn.execute("UPDATE phones SET image_url = ? WHERE id = ?", (image_url, row["id"]))
            updated += 1

    candidate_rows = conn.execute(
        """
        SELECT c.id, p.image_url
        FROM candidates c
        JOIN phones p
          ON p.brand = c.brand
         AND p.country = c.source_country
         AND p.normalized_model = c.normalized_model
        WHERE (c.image_url IS NULL OR c.image_url = '')
          AND p.image_url IS NOT NULL
          AND p.image_url != ''
        """
    ).fetchall()
    for row in candidate_rows:
        if not db.is_bad_image_url(row["image_url"]):
            conn.execute("UPDATE candidates SET image_url = ? WHERE id = ?", (row["image_url"], row["id"]))
            updated += 1
    return updated


def enrich_missing_prices(conn: sqlite3.Connection, *, timeout: int = 25, limit: int = 80) -> int:
    updated = 0
    rows = conn.execute(
        """
        SELECT 'phones' AS table_name, id, source_url
        FROM phones
        WHERE price IS NULL OR price = ''
        UNION ALL
        SELECT 'candidates' AS table_name, id, source_url
        FROM candidates
        WHERE price IS NULL OR price = ''
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    for row in rows:
        try:
            price = best_price_from_page(row["source_url"], timeout=timeout)
        except Exception:
            continue
        if price:
            conn.execute(f"UPDATE {row['table_name']} SET price = ? WHERE id = ?", (price, row["id"]))
            updated += 1
    return updated


def dedupe_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = (
            row["brand"],
            row["country"],
            row["page_url"].rstrip("/"),
            clean_text(row["raw_title"]).lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def crawl_source(
    source: Source,
    *,
    max_pages: int = 6,
    delay_seconds: float = 1.0,
    timeout: int = 25,
) -> list[dict[str, Any]]:
    fetched_at = now_utc()
    all_rows: list[dict[str, Any]] = []
    queued: list[str] = []
    queued_scores: dict[str, int] = {}
    visited: set[str] = set()

    def collect_from_html(html: str, current_url: str, *, rendered: bool = False) -> list[dict[str, Any]]:
        parser = parse_html(html)
        rows: list[dict[str, Any]] = []
        rows.extend(brand_rows_from_html(html, source, current_url, fetched_at))
        rows.extend(promo_rows_from_html(html, source, current_url, fetched_at))
        rows.extend(teaser_rows_from_text(parser, html, source, current_url, fetched_at))
        rows.extend(page_rows(parser, source, current_url, fetched_at))
        if rendered:
            for row in rows:
                payload = row.get("raw_payload")
                if isinstance(payload, dict):
                    payload["rendered"] = True
        return rows

    for start_url in source.start_urls:
        if start_url in visited:
            continue
        visited.add(start_url)
        try:
            html = fetch_html(start_url, timeout=timeout)
        except Exception as exc:
            print(f"[WARN] {source.name} start page failed: {start_url} ({exc})")
            continue
        if is_walmart_source(source, start_url):
            all_rows.extend(walmart_rows_from_html(html, source, start_url, fetched_at))
            for page in range(2, max(1, max_pages) + 1):
                page_url = walmart_page_url(start_url, page)
                if page_url in visited:
                    continue
                visited.add(page_url)
                try:
                    page_html = fetch_html(page_url, timeout=timeout)
                except Exception:
                    continue
                all_rows.extend(walmart_rows_from_html(page_html, source, page_url, fetched_at))
                time.sleep(delay_seconds)
            time.sleep(delay_seconds)
            continue
        parser = parse_html(html)
        before_static = len(all_rows)
        all_rows.extend(collect_from_html(html, start_url))
        static_added = len(all_rows) - before_static
        if source.render:
            rendered_html = fetch_rendered_html(start_url, timeout=timeout)
            if rendered_html:
                before_render = len(all_rows)
                all_rows.extend(collect_from_html(rendered_html, start_url, rendered=True))
                print(
                    f"[RENDER] extracted {source.country}:{source.brand} {start_url} static_rows={static_added} rendered_rows={len(all_rows) - before_render}",
                    flush=True,
                )
        if is_gsmarena_source(source, start_url):
            all_rows.extend(gsmarena_rows(parser, source, start_url, fetched_at, limit=max(8, max_pages * 4)))
            time.sleep(delay_seconds)
            continue
        for link in parser.links:
            if is_interesting_link(source, start_url, link):
                absolute = urljoin(start_url, link.href).split("#", 1)[0]
                if absolute not in visited and absolute not in queued:
                    queued.append(absolute)
                    queued_scores[absolute] = link_priority(source, start_url, link)
        time.sleep(delay_seconds)

    queued.sort(key=lambda item: queued_scores.get(item, 0), reverse=True)
    for page_url in queued[:max_pages]:
        if page_url in visited:
            continue
        visited.add(page_url)
        try:
            html = fetch_html(page_url, timeout=timeout)
        except Exception:
            continue
        parser = parse_html(html)
        if is_walmart_source(source, page_url):
            all_rows.extend(walmart_rows_from_html(html, source, page_url, fetched_at))
            time.sleep(delay_seconds)
            continue
        all_rows.extend(brand_rows_from_html(html, source, page_url, fetched_at))
        all_rows.extend(promo_rows_from_html(html, source, page_url, fetched_at))
        all_rows.extend(teaser_rows_from_text(parser, html, source, page_url, fetched_at))
        all_rows.extend(page_rows(parser, source, page_url, fetched_at))
        time.sleep(delay_seconds)

    return dedupe_rows(all_rows)


def crawl_sources_to_db(
    conn: sqlite3.Connection,
    sources: list[Source],
    *,
    max_pages: int = 6,
    delay_seconds: float = 1.0,
    timeout: int = 25,
    run_id: int | None = None,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    set_custom_series_rules(db.custom_series_map(conn))
    total_sources = len(sources)
    for index, source in enumerate(sources, start=1):
        key = f"{source.country}:{source.brand}"
        print(
            f"[COLLECT] source {index}/{total_sources} start: {key} {source.name} urls={len(source.start_urls)}",
            flush=True,
        )
        try:
            rows = crawl_source(
                source,
                max_pages=max_pages,
                delay_seconds=delay_seconds,
                timeout=timeout,
            )
        except Exception as exc:
            counts[key] = 0
            print(f"[WARN] {source.name} crawl failed: {type(exc).__name__}: {exc}", flush=True)
            continue
        for row in rows:
            row["run_id"] = run_id
        counts[key] = db.insert_raw_items(conn, rows)
        print(f"[COLLECT] source {index}/{total_sources} done: {key} raw_rows={len(rows)} inserted={counts[key]}", flush=True)
    return counts
