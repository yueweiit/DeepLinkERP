from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import re
import sys
from typing import Any, Callable
from urllib.parse import quote, urljoin, urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from phone_watch.cleaning import clean_text  # noqa: E402
from phone_watch.crawler import USER_AGENT  # noqa: E402
from phone_watch import db as phone_watch_db  # noqa: E402

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional dependency in some debug environments
    BeautifulSoup = None


DEFAULT_NEWS_CONFIG = PROJECT_ROOT / "config" / "news_sources.json"
DEFAULT_OUT = PROJECT_ROOT / ".codex_tmp" / "ithome_playwright_today.json"
ITHOME_MOBILE_URL = "https://mobile.ithome.com/"
ITHOME_SEARCH_URL = "https://www.ithome.com/search/{keyword}.html"
ITHOME_TAG_URL = "https://www.ithome.com/tags/{keyword}/"
ARTICLE_HOSTS = {"www.ithome.com", "mobile.ithome.com"}
BRAND_SEARCH_MAX_ATTEMPTS = 3
SHORT_PAGE_HTML_LEN = 10000
SHORT_PAGE_TEXT_LEN = 100
BODY_PREVIEW_LEN = 80
BRAND_FALLBACK_SOURCE = "mobile_phone_keyword_filter"
LATEST_WHEN_NO_TODAY_FALLBACK = "latest_when_no_today"
LATEST_WHEN_NO_TODAY_LIMIT = 3
ITHOME_404_REDIRECT_WAIT_MS = 8000
ITHOME_404_REDIRECT_MARKERS = ("404错误", "没有找到页面", "自动返回IT之家首页")
SOURCE_TYPE_BY_PLAYWRIGHT_SOURCE = {
    "brand_tag": "ithome_brand_search",
    "brand_search": "ithome_brand_search",
    "brand_keyword": "ithome_brand_search",
    "mobile_phone": "ithome_phone_today",
}
SOURCE_NAME_BY_SOURCE_TYPE = {
    "ithome_brand_search": "IT之家品牌关键词搜索",
    "ithome_phone_today": "IT之家手机分区当日新闻",
}
BRAND_ALIAS_TERMS = {
    "HONOR": ["荣耀"],
    "HUAWEI": ["华为"],
    "MOTOROLA": ["摩托罗拉", "moto"],
    "OPPO": ["OPPO"],
    "SAMSUNG": ["三星", "Samsung"],
    "VIVO": ["vivo"],
    "XIAOMI": ["小米", "Redmi", "红米"],
    "ZTE": ["中兴", "努比亚", "红魔"],
}


@dataclass(frozen=True)
class FetchSource:
    source: str
    url: str
    keyword: str | None = None
    brand: str | None = None
    fallback_url: str | None = None
    fallback_source: str | None = None


def is_ithome_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower() in ARTICLE_HOSTS and bool(re.search(r"/\d+/\d+/\d+\.htm$", parsed.path))


def article_date_from_text(text: str, today: date) -> str | None:
    normalized = clean_text(text)
    if not normalized:
        return None
    if any(token in normalized for token in ("今日", "刚刚", "分钟前", "小时前")):
        return today.isoformat()
    if "昨日" in normalized:
        return None

    full_date = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?", normalized)
    if full_date:
        candidate = safe_date(int(full_date.group(1)), int(full_date.group(2)), int(full_date.group(3)))
        if candidate is None:
            return None
        return candidate.isoformat() if candidate == today else None

    month_day = re.search(r"(\d{1,2})月(\d{1,2})日", normalized)
    if month_day:
        candidate = safe_date(today.year, int(month_day.group(1)), int(month_day.group(2)))
        if candidate is None:
            return None
        if candidate > today:
            candidate = date(today.year - 1, candidate.month, candidate.day)
        return candidate.isoformat() if candidate == today else None

    slash_date = re.search(r"(\d{1,2})[/-](\d{1,2})(?![/-]\d)", normalized)
    if slash_date:
        candidate = safe_date(today.year, int(slash_date.group(1)), int(slash_date.group(2)))
        if candidate is None:
            return None
        return candidate.isoformat() if candidate == today else None

    return None


def article_any_date_from_text(text: str, today: date) -> str | None:
    normalized = clean_text(text)
    if not normalized:
        return None
    if any(token in normalized for token in ("今日", "刚刚", "分钟前", "小时前")):
        return today.isoformat()
    if "昨日" in normalized:
        return (today - timedelta(days=1)).isoformat()

    full_date = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?", normalized)
    if full_date:
        candidate = safe_date(int(full_date.group(1)), int(full_date.group(2)), int(full_date.group(3)))
        return candidate.isoformat() if candidate else None

    month_day = re.search(r"(\d{1,2})月(\d{1,2})日", normalized)
    if month_day:
        candidate = safe_date(today.year, int(month_day.group(1)), int(month_day.group(2)))
        if candidate and candidate > today:
            candidate = date(today.year - 1, candidate.month, candidate.day)
        return candidate.isoformat() if candidate else None

    slash_date = re.search(r"(\d{1,2})[/-](\d{1,2})(?![/-]\d)", normalized)
    if slash_date:
        candidate = safe_date(today.year, int(slash_date.group(1)), int(slash_date.group(2)))
        return candidate.isoformat() if candidate else None

    return None


def safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def html_fragment_text(html: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", html))


def body_preview_from_html(html: str) -> str:
    return html_fragment_text(html)[:BODY_PREVIEW_LEN]


def is_ithome_404_redirect_page(html: str) -> bool:
    text = html_fragment_text(html or "")
    return all(marker in text for marker in ITHOME_404_REDIRECT_MARKERS)


def should_retry_short_brand_page(source: FetchSource, html: str, text_len: int, items_count: int) -> bool:
    if source.source != "brand_keyword" or items_count > 0:
        return False
    return len(html or "") < SHORT_PAGE_HTML_LEN or text_len < SHORT_PAGE_TEXT_LEN


def brand_match_terms(keyword: str | None, brand: str | None) -> list[str]:
    terms: list[str] = []
    if keyword:
        terms.append(keyword)
        if keyword.endswith("手机"):
            terms.append(keyword[: -len("手机")])
    if brand:
        terms.extend(BRAND_ALIAS_TERMS.get(brand.upper(), []))
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = clean_text(term)
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def filter_mobile_items_for_brand(mobile_items: list[dict[str, str]], source: FetchSource) -> list[dict[str, str]]:
    terms = brand_match_terms(source.keyword, source.brand)
    if not terms:
        return []
    fallback_items: list[dict[str, str]] = []
    lowered_terms = [term.casefold() for term in terms]
    for item in mobile_items:
        title = clean_text(item.get("title", ""))
        if not any(term in title.casefold() for term in lowered_terms):
            continue
        fallback_item = dict(item)
        fallback_item["source"] = source.source
        fallback_item["fallback"] = BRAND_FALLBACK_SOURCE
        fallback_item["fallback_of"] = source.url
        if source.keyword:
            fallback_item["keyword"] = source.keyword
        if source.brand:
            fallback_item["brand"] = source.brand
        fallback_items.append(fallback_item)
    return fallback_items


def context_date_text(node: Any) -> str:
    if node is None:
        return ""
    if BeautifulSoup is not None:
        date_texts: list[str] = []
        for attr in ("data-ot", "datetime", "data-time", "time"):
            value = node.get(attr) if hasattr(node, "get") else None
            if value:
                date_texts.append(str(value))
        for selector in (".state", ".d", "time", "[data-ot]", "[datetime]", "[data-time]"):
            for candidate in node.select(selector):
                for attr in ("data-ot", "datetime", "data-time", "time"):
                    value = candidate.get(attr)
                    if value:
                        date_texts.append(str(value))
                text = clean_text(candidate.get_text(" ", strip=True))
                if text:
                    date_texts.append(text)
        if date_texts:
            return clean_text(" ".join(date_texts))
        for candidate in node.find_all(["span", "time", "em", "i"]):
            text = clean_text(candidate.get_text(" ", strip=True))
            if re.search(r"\d{4}[-年]\d{1,2}[-月]\d{1,2}|(?:今|昨)日|刚刚|分钟前|小时前|\d{1,2}月\d{1,2}日|\d{1,2}[/-]\d{1,2}", text):
                date_texts.append(text)
        return clean_text(" ".join(date_texts))
    return html_fragment_text(str(node))


def today_state_text(node: Any) -> str:
    if node is None or BeautifulSoup is None:
        return ""
    texts: list[str] = []
    for selector in (".d .state", ".state"):
        for candidate in node.select(selector):
            text = clean_text(candidate.get_text(" ", strip=True))
            if text:
                texts.append(text)
    return clean_text(" ".join(texts))


def node_data_ot(node: Any) -> str:
    if node is None or BeautifulSoup is None:
        return ""
    candidates = [node]
    if hasattr(node, "find_all"):
        candidates.extend(node.find_all(attrs={"data-ot": True}))
    for candidate in candidates:
        value = candidate.get("data-ot") if hasattr(candidate, "get") else None
        if value:
            return str(value).strip()
    return ""


def html_data_ot(block: str) -> str:
    content = block or ""
    match = re.search(
        r"<div\b[^>]*\bclass\s*=\s*(['\"])[^'\"]*\bc\b[^'\"]*\1[^>]*\bdata-ot\s*=\s*(['\"])(.*?)\2",
        content,
        flags=re.S | re.I,
    )
    if match:
        return match.group(3).strip()
    match = re.search(r"\bdata-ot\s*=\s*(['\"])(.*?)\1", content, flags=re.S | re.I)
    return match.group(2).strip() if match else ""


def normalize_data_ot(value: str | None) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if re.match(r"^\d{4}-\d{2}-\d{2}T", text):
        return text
    return None


def parse_data_ot_datetime(value: str | None) -> datetime | None:
    normalized = normalize_data_ot(value)
    if not normalized:
        return None
    candidate = normalized
    match = re.match(r"^(.*?\.)(\d{6})\d+([+-]\d{2}:\d{2}|Z)$", candidate)
    if match:
        candidate = f"{match.group(1)}{match.group(2)}{match.group(3)}"
    if candidate.endswith("Z"):
        candidate = f"{candidate[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def is_in_collect_window(published_at: str, window_start: str | None, window_end: str | None) -> bool:
    published_dt = parse_data_ot_datetime(published_at)
    if published_dt is None:
        return False
    if window_start:
        start_dt = parse_data_ot_datetime(window_start)
        if start_dt is None or published_dt <= start_dt:
            return False
    if window_end:
        end_dt = parse_data_ot_datetime(window_end)
        if end_dt is None or published_dt > end_dt:
            return False
    return True


def html_date_context_text(block: str) -> str:
    texts: list[str] = []
    for match in re.finditer(
        r"\b(?:data-ot|datetime|data-time|time)\s*=\s*(['\"])(.*?)\1",
        block or "",
        flags=re.S | re.I,
    ):
        texts.append(match.group(2))
    for match in re.finditer(
        r"<(?:span|div|time|em|i)\b[^>]*(?:class\s*=\s*['\"][^'\"]*(?:state|d|time)[^'\"]*['\"]|datetime|data-ot|data-time)[^>]*>([\s\S]*?)</(?:span|div|time|em|i)>",
        block or "",
        flags=re.S | re.I,
    ):
        text = html_fragment_text(match.group(1))
        if text:
            texts.append(text)
    if texts:
        return clean_text(" ".join(texts))
    for match in re.finditer(r"<(?:span|time|em|i)\b[^>]*>([\s\S]*?)</(?:span|time|em|i)>", block or "", flags=re.S | re.I):
        text = html_fragment_text(match.group(1))
        if re.search(r"\d{4}[-年]\d{1,2}[-月]\d{1,2}|(?:今|昨)日|刚刚|分钟前|小时前|\d{1,2}月\d{1,2}日|\d{1,2}[/-]\d{1,2}", text):
            texts.append(text)
    return clean_text(" ".join(texts))


def html_today_state_text(block: str) -> str:
    texts: list[str] = []
    for match in re.finditer(
        r"<span\b[^>]*class\s*=\s*(['\"])[^'\"]*\bstate\b[^'\"]*\1[^>]*>([\s\S]*?)</span>",
        block or "",
        flags=re.S | re.I,
    ):
        text = html_fragment_text(match.group(2))
        if text:
            texts.append(text)
    return clean_text(" ".join(texts))


def html_article_blocks(html: str) -> list[str]:
    content = html or ""
    blocks: list[str] = []
    list_match = re.search(r"<div\b[^>]*\bid\s*=\s*(['\"])list\1[\s\S]*?</ul>", content, flags=re.I)
    if list_match:
        blocks.extend(re.findall(r"<li\b[\s\S]*?</li>", list_match.group(0), flags=re.I))
    for tag in ("article", "li", "section", "div"):
        blocks.extend(re.findall(fr"<{tag}\b[\s\S]*?</{tag}>", content, flags=re.I))
    return blocks


def item_to_article(
    *,
    title: str,
    href: str,
    state_text: str,
    data_ot: str | None,
    base_url: str,
    source: str,
    today: date,
    keyword: str | None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> dict[str, str] | None:
    absolute = urljoin(base_url, href).split("#", 1)[0].rstrip("/")
    if not title or not is_ithome_article_url(absolute):
        return None
    published_at = normalize_data_ot(data_ot)
    if not published_at or "今日" not in clean_text(state_text):
        return None
    article_date = published_at[:10]
    if article_date != today.isoformat():
        return None
    if not is_in_collect_window(published_at, window_start, window_end):
        return None
    row = {
        "date": article_date,
        "published_at": published_at,
        "title": clean_text(title),
        "url": absolute,
        "source": source,
    }
    if keyword:
        row["keyword"] = keyword
    return row


def latest_item_to_article(
    *,
    title: str,
    href: str,
    context_text: str,
    base_url: str,
    source: str,
    requested_date: date,
    keyword: str | None,
    data_ot: str | None = None,
) -> dict[str, str] | None:
    absolute = urljoin(base_url, href).split("#", 1)[0].rstrip("/")
    if not title or not is_ithome_article_url(absolute):
        return None
    row = {
        "title": clean_text(title),
        "url": absolute,
        "source": source,
        "fallback": LATEST_WHEN_NO_TODAY_FALLBACK,
        "requested_date": requested_date.isoformat(),
    }
    article_date = article_any_date_from_text(context_text, requested_date)
    published_at = normalize_data_ot(data_ot)
    if published_at:
        row["date"] = published_at[:10]
        row["published_at"] = published_at
    elif article_date:
        row["date"] = article_date
    if keyword:
        row["keyword"] = keyword
    return row


def extract_today_articles_bs4(
    html: str,
    base_url: str,
    *,
    source: str,
    today: date,
    keyword: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> list[dict[str, str]]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict[str, str]] = []

    for item in soup.select("#list .fl ul.bl li"):
        anchor = item.select_one("a.title[href]")
        if anchor is None:
            continue
        row = item_to_article(
            title=str(anchor.get("title") or anchor.get_text(" ", strip=True)),
            href=str(anchor.get("href") or ""),
            state_text=today_state_text(item),
            data_ot=node_data_ot(item),
            base_url=base_url,
            source=source,
            today=today,
            keyword=keyword,
            window_start=window_start,
            window_end=window_end,
        )
        if row:
            rows.append(row)

    for container_selector in ("article", "li", ".item", ".list-item", "section"):
        for item in soup.select(container_selector):
            anchor = item.select_one("a.title[href]") or item.select_one("a[href]")
            if anchor is None:
                continue
            row = item_to_article(
                title=str(anchor.get("title") or anchor.get_text(" ", strip=True)),
                href=str(anchor.get("href") or ""),
                state_text=today_state_text(item),
                data_ot=node_data_ot(item),
                base_url=base_url,
                source=source,
                today=today,
                keyword=keyword,
                window_start=window_start,
                window_end=window_end,
            )
            if row:
                rows.append(row)

    return dedupe_articles(rows)


def extract_latest_articles_bs4(
    html: str,
    base_url: str,
    *,
    source: str,
    requested_date: date,
    keyword: str | None = None,
    limit: int = LATEST_WHEN_NO_TODAY_LIMIT,
) -> list[dict[str, str]]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html or "", "html.parser")
    rows: list[dict[str, str]] = []

    for item in soup.select("#list .fl ul.bl li"):
        anchor = item.select_one("a.title[href]")
        if anchor is None:
            continue
        row = latest_item_to_article(
            title=str(anchor.get("title") or anchor.get_text(" ", strip=True)),
            href=str(anchor.get("href") or ""),
            context_text=context_date_text(item),
            base_url=base_url,
            source=source,
            requested_date=requested_date,
            keyword=keyword,
            data_ot=node_data_ot(item),
        )
        if row:
            rows.append(row)
        if len(dedupe_articles(rows)) >= limit:
            break

    if len(dedupe_articles(rows)) < limit:
        for container_selector in ("article", "li", ".item", ".list-item", "section"):
            for item in soup.select(container_selector):
                anchor = item.select_one("a.title[href]") or item.select_one("a[href]")
                if anchor is None:
                    continue
                row = latest_item_to_article(
                    title=str(anchor.get("title") or anchor.get_text(" ", strip=True)),
                    href=str(anchor.get("href") or ""),
                    context_text=context_date_text(item),
                    base_url=base_url,
                    source=source,
                    requested_date=requested_date,
                    keyword=keyword,
                    data_ot=node_data_ot(item),
                )
                if row:
                    rows.append(row)
                if len(dedupe_articles(rows)) >= limit:
                    break
            if len(dedupe_articles(rows)) >= limit:
                break

    return dedupe_articles(rows)[:limit]


def extract_today_articles_regex(
    html: str,
    base_url: str,
    *,
    source: str,
    today: date,
    keyword: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    blocks = html_article_blocks(html)

    for block in blocks:
        anchor = re.search(r"<a\b([^>]*\bclass\s*=\s*['\"][^'\"]*\btitle\b[^'\"]*['\"][^>]*)>(.*?)</a>", block, flags=re.S | re.I)
        if not anchor:
            anchor = re.search(r"<a\b([^>]*)>(.*?)</a>", block, flags=re.S | re.I)
        if not anchor:
            continue
        href_match = re.search(r"\bhref\s*=\s*(['\"])(.*?)\1", anchor.group(1), flags=re.S | re.I)
        title_match = re.search(r"\btitle\s*=\s*(['\"])(.*?)\1", anchor.group(1), flags=re.S | re.I)
        href = href_match.group(2) if href_match else ""
        title = title_match.group(2) if title_match else html_fragment_text(anchor.group(2))
        row = item_to_article(
            title=title,
            href=href,
            state_text=html_today_state_text(block),
            data_ot=html_data_ot(block),
            base_url=base_url,
            source=source,
            today=today,
            keyword=keyword,
            window_start=window_start,
            window_end=window_end,
        )
        if row:
            rows.append(row)
    return dedupe_articles(rows)


def extract_latest_articles_regex(
    html: str,
    base_url: str,
    *,
    source: str,
    requested_date: date,
    keyword: str | None = None,
    limit: int = LATEST_WHEN_NO_TODAY_LIMIT,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    blocks = html_article_blocks(html)

    for block in blocks:
        anchor = re.search(r"<a\b([^>]*\bclass\s*=\s*['\"][^'\"]*\btitle\b[^'\"]*['\"][^>]*)>(.*?)</a>", block, flags=re.S | re.I)
        if not anchor:
            anchor = re.search(r"<a\b([^>]*)>(.*?)</a>", block, flags=re.S | re.I)
        if not anchor:
            continue
        href_match = re.search(r"\bhref\s*=\s*(['\"])(.*?)\1", anchor.group(1), flags=re.S | re.I)
        title_match = re.search(r"\btitle\s*=\s*(['\"])(.*?)\1", anchor.group(1), flags=re.S | re.I)
        href = href_match.group(2) if href_match else ""
        title = title_match.group(2) if title_match else html_fragment_text(anchor.group(2))
        row = latest_item_to_article(
            title=title,
            href=href,
            context_text=html_date_context_text(block),
            base_url=base_url,
            source=source,
            requested_date=requested_date,
            keyword=keyword,
            data_ot=html_data_ot(block),
        )
        if row:
            rows.append(row)
        if len(dedupe_articles(rows)) >= limit:
            break
    return dedupe_articles(rows)[:limit]


def extract_today_articles(
    html: str,
    base_url: str,
    *,
    source: str,
    today: date,
    keyword: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
) -> list[dict[str, str]]:
    rows = extract_today_articles_bs4(
        html,
        base_url,
        source=source,
        today=today,
        keyword=keyword,
        window_start=window_start,
        window_end=window_end,
    )
    if rows:
        return rows
    return extract_today_articles_regex(
        html,
        base_url,
        source=source,
        today=today,
        keyword=keyword,
        window_start=window_start,
        window_end=window_end,
    )


def extract_latest_articles(
    html: str,
    base_url: str,
    *,
    source: str,
    requested_date: date,
    keyword: str | None = None,
    limit: int = LATEST_WHEN_NO_TODAY_LIMIT,
) -> list[dict[str, str]]:
    rows = extract_latest_articles_bs4(
        html,
        base_url,
        source=source,
        requested_date=requested_date,
        keyword=keyword,
        limit=limit,
    )
    if rows:
        return rows
    return extract_latest_articles_regex(
        html,
        base_url,
        source=source,
        requested_date=requested_date,
        keyword=keyword,
        limit=limit,
    )


def dedupe_articles(items: list[dict[str, str]]) -> list[dict[str, str]]:
    deduped: list[dict[str, str]] = []
    indexes: dict[str, int] = {}
    seen: set[str] = set()
    for item in items:
        url = item.get("url", "").split("#", 1)[0].rstrip("/")
        if not url or url in seen:
            if url and item_rank(item) > item_rank(deduped[indexes[url]]):
                copy = dict(item)
                copy["url"] = url
                deduped[indexes[url]] = copy
            continue
        seen.add(url)
        indexes[url] = len(deduped)
        copy = dict(item)
        copy["url"] = url
        deduped.append(copy)
    return deduped


def item_rank(item: dict[str, str]) -> int:
    score = 0
    if item.get("brand"):
        score += 1
    if item.get("fallback"):
        score += 2
    return score


def load_sources(config_path: Path) -> list[FetchSource]:
    with config_path.open("r", encoding="utf-8") as file:
        config = json.load(file)
    sources = [FetchSource(source="mobile_phone", url=ITHOME_MOBILE_URL)]
    for source in config.get("sources", []):
        if str(source.get("source_type", "")).lower() != "ithome_brand_search":
            continue
        brand = str(source.get("brand") or "").upper() or None
        for keyword in source.get("search_keywords") or []:
            keyword_text = str(keyword).strip()
            if not keyword_text:
                continue
            sources.append(
                FetchSource(
                    source="brand_search",
                    url=ITHOME_SEARCH_URL.format(keyword=quote(keyword_text)),
                    keyword=keyword_text,
                    brand=brand,
                    fallback_url=ITHOME_TAG_URL.format(keyword=quote(keyword_text)),
                    fallback_source="brand_tag",
                )
            )
    return sources


def fetch_page_html(page: Any, source: FetchSource, *, timeout: int) -> tuple[str, int]:
    timeout_ms = max(timeout, 10) * 1000
    page.goto(source.url, wait_until="domcontentloaded", timeout=timeout_ms)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 12000))
    except Exception:
        pass
    for _ in range(2):
        page.mouse.wheel(0, 1000)
        page.wait_for_timeout(700)
    html = page.content()
    try:
        text_len = len(page.locator("body").inner_text(timeout=3000))
    except Exception:
        text_len = 0
    return html, text_len


def run_playwright_collect(
    *,
    sources: list[FetchSource],
    today: date,
    timeout: int,
    headed: bool,
    user_data_dir: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    playwright_factory: Callable[[], Any] | None = None,
    logger: Callable[[str], None] | None = None,
) -> dict[str, Any]:
    collect_window_end = window_end or datetime.now().astimezone().isoformat(timespec="seconds")
    if logger:
        logger(f"start date={today.isoformat()} sources={len(sources)} headed={headed} timeout={timeout}")
    if playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            if logger:
                logger(f"error source=playwright error=playwright not installed: {exc}")
            return {
                "status": "error",
                "date": today.isoformat(),
                "window_start": window_start,
                "window_end": collect_window_end,
                "items": [],
                "errors": [{"source": "playwright", "url": "", "error": f"playwright not installed: {exc}"}],
                "counts": {"sources": len(sources), "fetched": 0, "items": 0, "errors": 1},
            }
        playwright_factory = sync_playwright

    items: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    mobile_items: list[dict[str, str]] = []
    fetched = 0
    with playwright_factory() as playwright:
        context = None
        browser = None
        page_options = {
            "user_agent": USER_AGENT,
            "viewport": {"width": 1440, "height": 1200},
            "locale": "zh-CN",
        }
        if user_data_dir:
            context = playwright.chromium.launch_persistent_context(
                user_data_dir,
                headless=not headed,
                **page_options,
            )
            page = context.new_page()
        else:
            browser = playwright.chromium.launch(headless=not headed)
            page = browser.new_page(**page_options)
        for fetch_source in sources:
            try:
                max_attempts = BRAND_SEARCH_MAX_ATTEMPTS if fetch_source.source == "brand_keyword" else 1
                for attempt in range(1, max_attempts + 1):
                    active_source = fetch_source
                    if logger:
                        logger(
                            "fetch "
                            f"source={active_source.source} "
                            f"keyword={active_source.keyword or ''} "
                            f"brand={active_source.brand or ''} "
                            f"attempt={attempt}/{max_attempts} "
                            f"url={active_source.url}"
                    )
                    html, text_len = fetch_page_html(page, active_source, timeout=timeout)
                    fetched += 1
                    if is_ithome_404_redirect_page(html):
                        if fetch_source.fallback_url:
                            active_source = FetchSource(
                                source=fetch_source.fallback_source or fetch_source.source,
                                url=fetch_source.fallback_url,
                                keyword=fetch_source.keyword,
                                brand=fetch_source.brand,
                            )
                            if logger:
                                logger(
                                    "retry_404_redirect "
                                    f"source={fetch_source.source} "
                                    f"keyword={fetch_source.keyword or ''} "
                                    f"wait={ITHOME_404_REDIRECT_WAIT_MS}ms "
                                    f"next={active_source.source} "
                                    f"url={fetch_source.url} "
                                    f"next_url={active_source.url}"
                                )
                            page.wait_for_timeout(ITHOME_404_REDIRECT_WAIT_MS)
                            html, text_len = fetch_page_html(page, active_source, timeout=timeout)
                            fetched += 1
                        else:
                            if logger:
                                logger(
                                    "retry_404_redirect "
                                    f"source={fetch_source.source} "
                                    f"keyword={fetch_source.keyword or ''} "
                                    f"wait={ITHOME_404_REDIRECT_WAIT_MS}ms "
                                    f"url={fetch_source.url}"
                                )
                            page.wait_for_timeout(ITHOME_404_REDIRECT_WAIT_MS)
                            html, text_len = fetch_page_html(page, active_source, timeout=timeout)
                            fetched += 1
                    source_items = extract_today_articles(
                        html,
                        active_source.url,
                        source=active_source.source,
                        today=today,
                        keyword=active_source.keyword,
                        window_start=window_start,
                        window_end=collect_window_end,
                    )
                    for item in source_items:
                        if active_source.brand:
                            item["brand"] = active_source.brand
                        item["page_url"] = active_source.url
                        item["collect_window_start"] = window_start
                        item["collect_window_end"] = collect_window_end
                    if active_source.source == "mobile_phone":
                        mobile_items = [dict(item) for item in source_items]
                    items.extend(source_items)
                    if logger:
                        logger(
                            "fetched "
                            f"source={active_source.source} "
                            f"html_len={len(html)} "
                            f"text_len={text_len} "
                            f"items={len(source_items)} "
                            f"attempt={attempt}/{max_attempts} "
                            f"url={active_source.url}"
                        )
                    if source_items:
                        break

                    body_preview = body_preview_from_html(html)
                    error_message = f"no today articles parsed html_len={len(html)} text_len={text_len}"
                    if should_retry_short_brand_page(active_source, html, text_len, len(source_items)) and attempt < max_attempts:
                        if logger:
                            logger(
                                "retry "
                                f"source={active_source.source} "
                                f"keyword={active_source.keyword or ''} "
                                f"attempt={attempt}/{max_attempts} "
                                f"error={error_message} "
                                f"body_preview={body_preview} "
                                f"url={active_source.url}"
                            )
                        page.wait_for_timeout(1200 * attempt)
                        continue

                    fallback_items = filter_mobile_items_for_brand(mobile_items, active_source)
                    if fallback_items:
                        items.extend(fallback_items)
                        if logger:
                            logger(
                                "fallback "
                                f"source={active_source.source} "
                                f"keyword={active_source.keyword or ''} "
                                f"items={len(fallback_items)} "
                                f"fallback={BRAND_FALLBACK_SOURCE} "
                                f"url={active_source.url}"
                            )
                        errors.append(
                            {
                                "source": active_source.source,
                                "keyword": active_source.keyword or "",
                                "url": active_source.url,
                                "error": error_message,
                                "body_preview": body_preview,
                                "fallback": BRAND_FALLBACK_SOURCE,
                                "fallback_items": str(len(fallback_items)),
                            }
                        )
                        break

                    if logger:
                        logger(
                            "empty "
                            f"source={active_source.source} "
                            f"keyword={active_source.keyword or ''} "
                            f"error={error_message} "
                            f"body_preview={body_preview} "
                            f"url={active_source.url}"
                        )
                    errors.append(
                        {
                            "source": active_source.source,
                            "keyword": active_source.keyword or "",
                            "url": active_source.url,
                            "error": error_message,
                            "body_preview": body_preview,
                        }
                    )
                    break
            except Exception as exc:
                if logger:
                    logger(
                        "error "
                        f"source={fetch_source.source} "
                        f"keyword={fetch_source.keyword or ''} "
                        f"error={type(exc).__name__}: {exc} "
                        f"url={fetch_source.url}"
                    )
                errors.append(
                    {
                        "source": fetch_source.source,
                        "keyword": fetch_source.keyword or "",
                        "url": fetch_source.url,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        if context is not None:
            context.close()
        elif browser is not None:
            browser.close()

    items = dedupe_articles(items)
    status = "ok" if not errors else ("partial_error" if items else "error")
    result = {
        "status": status,
        "date": today.isoformat(),
        "window_start": window_start,
        "window_end": collect_window_end,
        "items": items,
        "errors": errors,
        "counts": {
            "sources": len(sources),
            "fetched": fetched,
            "items": len(items),
            "errors": len(errors),
        },
    }
    if logger:
        logger(
            "done "
            f"status={result['status']} "
            f"sources={result['counts']['sources']} "
            f"fetched={result['counts']['fetched']} "
            f"items={result['counts']['items']} "
            f"errors={result['counts']['errors']}"
        )
    return result


def write_result(result: dict[str, Any], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    ascii_path = out_path.with_name(f"{out_path.stem}.ascii{out_path.suffix}")
    ascii_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")


def item_to_news_row(
    item: dict[str, Any],
    *,
    imported_at: str,
    result_date: str,
    result_window_start: str | None = None,
    result_window_end: str | None = None,
) -> dict[str, Any] | None:
    source_type = SOURCE_TYPE_BY_PLAYWRIGHT_SOURCE.get(str(item.get("source") or ""))
    if not source_type:
        return None
    brand = str(item.get("brand") or "").strip().upper()
    if not brand and source_type == "ithome_phone_today":
        brand = "ALL"
    if not brand:
        return None
    fallback = str(item.get("fallback") or "").strip()
    requested_date = str(item.get("requested_date") or result_date)
    item_date = str(item.get("date") or "").strip()
    item_published_at = str(item.get("published_at") or "").strip()
    published_at = item_published_at or (f"{item_date}T00:00:00+00:00" if item_date else None)
    seen_date = (published_at[:10] if published_at else None) or item_date or requested_date or result_date
    collect_window_start = item.get("collect_window_start") or result_window_start
    collect_window_end = item.get("collect_window_end") or result_window_end or imported_at
    last_error = None
    if fallback:
        last_error = f"{fallback}; requested_date={requested_date}"
    return {
        "brand": brand,
        "source_type": source_type,
        "source_name": SOURCE_NAME_BY_SOURCE_TYPE[source_type],
        "title": str(item.get("title") or ""),
        "url": str(item.get("url") or ""),
        "first_collected_at": imported_at,
        "last_collected_at": imported_at,
        "seen_date": seen_date,
        "published_at": published_at,
        "collect_window_start": collect_window_start,
        "collect_window_end": collect_window_end,
        "last_error": last_error,
    }


def import_result_to_db(
    result: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    db_module: Any = phone_watch_db,
    imported_at: str | None = None,
) -> dict[str, int]:
    target_db = db_path if db_path is not None else db_module.DEFAULT_DB
    timestamp = imported_at or datetime.now().astimezone().isoformat(timespec="seconds")
    result_date = str(result.get("date") or timestamp[:10])
    result_window_start = result.get("window_start")
    result_window_end = result.get("window_end")
    counts = {"items": len(result.get("items") or []), "upserted": 0, "skipped": 0, "cleanup_deleted": 0}
    db_module.init_db(target_db)
    with db_module.connect(target_db) as conn:
        for item in result.get("items") or []:
            row = item_to_news_row(
                item,
                imported_at=timestamp,
                result_date=result_date,
                result_window_start=str(result_window_start) if result_window_start else None,
                result_window_end=str(result_window_end) if result_window_end else None,
            )
            if row is None:
                counts["skipped"] += 1
                continue
            try:
                db_module.upsert_news_item(conn, row)
            except ValueError:
                counts["skipped"] += 1
                continue
            counts["upserted"] += 1
        cleanup = getattr(db_module, "cleanup_old_news_items", None)
        if cleanup is not None:
            counts["cleanup_deleted"] = int(cleanup(conn, retention_days=7, now=timestamp))
    return counts


def result_to_stdout_json(result: dict[str, Any]) -> str:
    return json.dumps(result, ensure_ascii=True, indent=2)


def run_login_session(
    *,
    user_data_dir: str,
    wait_seconds: int,
    playwright_factory: Callable[[], Any] | None = None,
) -> None:
    if playwright_factory is None:
        from playwright.sync_api import sync_playwright

        playwright_factory = sync_playwright

    with playwright_factory() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir,
            headless=False,
            locale="zh-CN",
            viewport={"width": 1440, "height": 1200},
            user_agent=USER_AGENT,
        )
        page = context.new_page()
        try:
            page.goto("https://www.ithome.com/", wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(max(1, int(wait_seconds)) * 1000)
        finally:
            context.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Playwright crawl IT之家 today phone news and brand keyword pages.")
    parser.add_argument("--date", default=date.today().isoformat(), help="只保留该日期文章，格式 YYYY-MM-DD")
    parser.add_argument("--news-config", default=str(DEFAULT_NEWS_CONFIG), help="新闻来源配置文件")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help="JSON 输出文件")
    parser.add_argument("--timeout", type=int, default=20, help="单页面超时秒数")
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，默认无头")
    parser.add_argument("--user-data-dir", help="复用 Playwright/Chromium 用户数据目录，用于保留手动登录态")
    parser.add_argument("--login-wait-seconds", type=int, help="只打开登录窗口并等待指定秒数，不执行采集")
    parser.add_argument("--import-db", action="store_true", help="采集完成后写入当前 phone_watch 数据库后端的 news_items")
    parser.add_argument("--db", default=str(phone_watch_db.DEFAULT_DB), help="仅 SQLite 后端使用；PG 后端由环境变量控制")
    parser.add_argument("--quiet", action="store_true", help="不输出过程日志，仅保留 JSON 输出")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.login_wait_seconds is not None:
        if not args.user_data_dir:
            print(json.dumps({"status": "error", "error": "--login-wait-seconds requires --user-data-dir"}, ensure_ascii=False), flush=True)
            return 2
        run_login_session(user_data_dir=args.user_data_dir, wait_seconds=args.login_wait_seconds)
        print(json.dumps({"status": "ok", "user_data_dir": args.user_data_dir}, ensure_ascii=True), flush=True)
        return 0

    try:
        target_date = date.fromisoformat(args.date)
    except ValueError:
        print(json.dumps({"status": "error", "error": f"invalid --date: {args.date}"}, ensure_ascii=False), flush=True)
        return 2

    sources = load_sources(Path(args.news_config))
    result = run_playwright_collect(
        sources=sources,
        today=target_date,
        timeout=args.timeout,
        headed=bool(args.headed),
        user_data_dir=args.user_data_dir,
        logger=None if args.quiet else lambda message: print(f"[ITHOME_PLAYWRIGHT] {message}", file=sys.stderr, flush=True),
    )
    write_result(result, Path(args.out))
    if args.import_db:
        import_counts = import_result_to_db(result, db_path=args.db)
        result["import"] = import_counts
        write_result(result, Path(args.out))
        if not args.quiet:
            print(
                "[ITHOME_PLAYWRIGHT] "
                f"import-db items={import_counts['items']} "
                f"upserted={import_counts['upserted']} "
                f"skipped={import_counts['skipped']}",
                file=sys.stderr,
                flush=True,
            )
    print(result_to_stdout_json(result), flush=True)
    return 0 if result["status"] in {"ok", "partial_error"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
