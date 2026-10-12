from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from html import unescape
from inspect import Parameter, signature
import re
import random
import time
from typing import Any, Callable, Literal
from urllib.parse import quote, unquote, urljoin, urlparse

from . import db
from .cleaning import clean_text
from .config import NewsConfig, NewsSource
from .crawler import fetch_html, fetch_ithome_search_html, fetch_ithome_search_html_like_user, fetch_rendered_html, parse_html

try:
    from bs4 import BeautifulSoup
except ImportError:  # pragma: no cover - optional until Docker image is rebuilt
    BeautifulSoup = None


NEWS_SOURCE_TYPES = {"ithome_brand_search", "ithome_phone_today"}
GENERAL_NEWS_BRAND = "ALL"
IT_HOME_SEARCH_URL = "https://www.ithome.com/search/{keyword}.html"
IT_HOME_TAG_URL = "https://www.ithome.com/tags/{keyword}/"
IT_HOME_SEARCH_DELAY_RANGE = (8, 20)
IT_HOME_SEARCH_COOLDOWN_EVERY = 3
IT_HOME_SEARCH_COOLDOWN_RANGE = (30, 60)
IT_HOME_DETAIL_DELAY_RANGE = (1.5, 4)
MOBILE_KEYWORD_FALLBACK_ERROR = "brand tag failed or empty; used mobile_phone_keyword_filter"


RenderMode = Literal["config", "always", "never", "playwright"]
FetchResult = str | tuple[str, dict[str, int]]
Fetcher = Callable[..., FetchResult]
BrowserSearchFetcher = Callable[..., FetchResult | None]


@dataclass(frozen=True)
class IthomeSearchCandidate:
    title: str
    url: str
    state_text: str = ""
    seen_date: str | None = None
    published_at: str | None = None


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def make_news_row(
    *,
    brand: str,
    source_type: str,
    source_name: str,
    title: str,
    url: str,
    seen_date: str | None = None,
    collected_at: str | None = None,
    published_at: str | None = None,
    collect_run_id: int | None = None,
    collect_window_start: str | None = None,
    collect_window_end: str | None = None,
) -> dict[str, Any]:
    timestamp = collected_at or utc_now()
    return {
        "brand": brand.upper(),
        "source_type": source_type.lower(),
        "source_name": source_name,
        "title": clean_text(title),
        "url": url,
        "first_collected_at": timestamp,
        "last_collected_at": timestamp,
        "seen_date": seen_date or timestamp[:10],
        "published_at": published_at,
        "collect_run_id": collect_run_id,
        "collect_window_start": collect_window_start,
        "collect_window_end": collect_window_end,
    }


def normalized_news_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row["brand"]).upper(),
        str(row["source_type"]).lower(),
        clean_text(str(row["title"])).lower(),
        canonical_url(str(row["url"])),
    )


def canonical_url(url: str) -> str:
    return url.split("#", 1)[0].rstrip("/")


def dedupe_news_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in rows:
        key = normalized_news_key(row)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped


def is_http_url(url: str) -> bool:
    return url.startswith(("http://", "https://"))


def is_ithome_news_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in {"www.ithome.com", "mobile.ithome.com"}:
        return False
    return bool(re.search(r"/\d+/\d+/\d+\.htm$", parsed.path))


def parse_news_links_from_html(
    html: str,
    base_url: str,
    *,
    brand: str,
    source_type: str,
    source_name: str,
    seen_date: str | None = None,
    collected_at: str | None = None,
    window_end: str | None = None,
) -> list[dict[str, Any]]:
    normalized_source_type = source_type.lower()
    if normalized_source_type == "ithome_brand_search":
        search_rows = parse_ithome_brand_search_page(
            html,
            base_url,
            brand=brand,
            source_type=normalized_source_type,
            source_name=source_name,
            seen_date=seen_date,
            collected_at=collected_at,
            window_end=window_end,
        )
        if search_rows:
            return search_rows

    parser = parse_html(html)
    rows: list[dict[str, Any]] = []
    for link in parser.links:
        title = clean_text(f"{link.text} {link.title}").strip()
        href = (link.href or "").strip()
        if not title or not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = canonical_url(urljoin(base_url, href))
        if not is_http_url(absolute):
            continue
        if normalized_source_type == "ithome_brand_search":
            if not is_ithome_news_url(absolute):
                continue
        rows.append(
            make_news_row(
                brand=brand,
                source_type=normalized_source_type,
                source_name=source_name,
                title=title,
                url=absolute,
                seen_date=seen_date,
                collected_at=collected_at,
            )
        )
    return dedupe_news_rows(rows)


def html_fragment_text(fragment: str) -> str:
    return clean_text(re.sub(r"<[^>]+>", " ", unescape(fragment)))


def html_attr(tag: str, name: str) -> str:
    match = re.search(rf"\b{name}\s*=\s*(['\"])(.*?)\1", tag, flags=re.S | re.I)
    return unescape(match.group(2)) if match else ""


def is_ithome_search_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.netloc.lower() == "www.ithome.com" and parsed.path.startswith("/search/")


def ithome_search_keyword_from_url(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.netloc.lower() != "www.ithome.com":
        return None
    match = re.match(r"^/search/(.+)\.html$", parsed.path)
    if not match:
        return None
    keyword = unquote(match.group(1)).strip()
    return keyword or None


def throttle_ithome_search_request(
    request_count: int,
    *,
    sleeper: Callable[[float], None] = time.sleep,
    random_uniform: Callable[[float, float], float] = random.uniform,
) -> None:
    delay = random_uniform(*IT_HOME_SEARCH_DELAY_RANGE)
    print(
        f"[THROTTLE] ithome search delay={delay:.1f}s request={request_count}",
        flush=True,
    )
    sleeper(delay)
    if request_count % IT_HOME_SEARCH_COOLDOWN_EVERY == 0:
        cooldown = random_uniform(*IT_HOME_SEARCH_COOLDOWN_RANGE)
        print(
            f"[THROTTLE] ithome search cooldown={cooldown:.1f}s after_requests={request_count}",
            flush=True,
        )
        sleeper(cooldown)


def soup_select_items(html: str):
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    return soup.select("#list .fl ul.bl li")


def html_title_text(html: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        return soup.title.get_text(" ", strip=True) if soup.title else ""
    match = re.search(r"<title\b[^>]*>(.*?)</title>", html or "", flags=re.S | re.I)
    return html_fragment_text(match.group(1)) if match else ""


def html_meta_content(html: str, *names: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for name in names:
            tag = soup.find("meta", attrs={"property": name}) or soup.find("meta", attrs={"name": name})
            if tag is not None:
                content = clean_text(str(tag.get("content") or ""))
                if content:
                    return content
        return ""
    for name in names:
        pattern = (
            rf"<meta\b(?=[^>]*(?:property|name)\s*=\s*['\"]{re.escape(name)}['\"])(?=[^>]*content\s*=\s*(['\"])(.*?)\1)[^>]*>"
        )
        match = re.search(pattern, html or "", flags=re.S | re.I)
        if match:
            return clean_text(unescape(match.group(2)))
    return ""


def html_canonical_url(html: str, base_url: str) -> str:
    href = ""
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        canonical = soup.find("link", rel=lambda value: value and "canonical" in str(value).lower())
        href = str(canonical.get("href") or "").strip() if canonical is not None else ""
    else:
        match = re.search(
            r"<link\b(?=[^>]*\brel\s*=\s*['\"][^'\"]*canonical[^'\"]*['\"])(?=[^>]*\bhref\s*=\s*(['\"])(.*?)\1)[^>]*>",
            html or "",
            flags=re.S | re.I,
        )
        href = unescape(match.group(2)).strip() if match else ""
    absolute = canonical_url(urljoin(base_url, href)) if href else canonical_url(base_url)
    return absolute if is_ithome_news_url(absolute) else canonical_url(base_url)


def ithome_detail_title_text(html: str) -> str:
    if BeautifulSoup is not None:
        soup = BeautifulSoup(html, "html.parser")
        for selector in ("h1.post_title", "h1"):
            node = soup.select_one(selector)
            if node is not None:
                title = clean_text(node.get_text(" ", strip=True))
                if title:
                    return title
        meta_title = html_meta_content(html, "og:title", "twitter:title")
        if meta_title:
            return meta_title
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        return clean_text(re.sub(r"[-_]\s*IT之家.*$", "", title))
    h1 = re.search(r"<h1\b[^>]*>(.*?)</h1>", html or "", flags=re.S | re.I)
    if h1:
        return html_fragment_text(h1.group(1))
    meta_title = html_meta_content(html, "og:title", "twitter:title")
    if meta_title:
        return meta_title
    return clean_text(re.sub(r"[-_]\s*IT之家.*$", "", html_title_text(html)))


def ithome_detail_published_at(html: str, *, window_end: str | None = None) -> str | None:
    meta_value = html_meta_content(
        html,
        "article:published_time",
        "pubdate",
        "publishdate",
        "publish_time",
        "date",
    )
    if meta_value:
        try:
            return parse_iso_datetime(meta_value).isoformat(timespec="seconds")
        except ValueError:
            if window_end:
                parsed = parse_ithome_published_at(meta_value, window_end=window_end)
                if parsed:
                    return parsed

    text = html_fragment_text(html or "")
    patterns = (
        r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?\s+(\d{1,2}):(\d{2})",
        r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        label = match.group(0)
        if window_end:
            parsed = parse_ithome_published_at(label, window_end=window_end)
            if parsed:
                return parsed
    return None


def is_ithome_detail_abnormal(html: str) -> bool:
    if "\u767b\u5f55\u8f6f\u5a92\u901a\u884c\u8bc1" in html_title_text(html):
        return True
    if ithome_detail_title_text(html):
        return False
    if html_meta_content(html, "article:published_time", "og:title"):
        return False
    return len(html or "") < 800


def ithome_search_has_result_items(html: str) -> bool:
    if BeautifulSoup is not None:
        return bool(soup_select_items(html))
    region = ithome_search_results_region(html)
    if not region:
        return False
    return bool(re.search(r"<li\b.*?\bclass\s*=\s*['\"][^'\"]*\btitle\b", region, flags=re.S | re.I))


def is_ithome_blocked_or_error(html: str) -> bool:
    if ithome_search_has_result_items(html):
        return False
    title = html_title_text(html)
    if "\u767b\u5f55\u8f6f\u5a92\u901a\u884c\u8bc1" in title:
        return True
    if len(html or "") < 5000:
        return True
    lowered = (html or "").lower()
    if "#list" not in lowered and 'id="list"' not in lowered and "id='list'" not in lowered and "class" not in lowered:
        return True
    if "ithome.com/0/" not in lowered and "mobile.ithome.com/0/" not in lowered and not re.search(r"/\d+/\d+/\d+\.htm", lowered):
        return True
    return False


def ithome_search_seen_date(label: str, default_seen_date: str | None) -> str | None:
    if not default_seen_date:
        return default_seen_date
    text = clean_text(label)
    if not text:
        return default_seen_date
    if "今日" in text or "刚刚" in text or "分钟前" in text or "小时前" in text:
        return default_seen_date
    try:
        base = date.fromisoformat(default_seen_date)
    except ValueError:
        return default_seen_date
    if "昨日" in text:
        return (base - timedelta(days=1)).isoformat()
    month_day = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if month_day:
        month = int(month_day.group(1))
        day = int(month_day.group(2))
        try:
            candidate = date(base.year, month, day)
        except ValueError:
            return default_seen_date
        if candidate > base:
            try:
                candidate = date(base.year - 1, month, day)
            except ValueError:
                return default_seen_date
        return candidate.isoformat()
    full_date = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?", text)
    if full_date:
        try:
            return date(int(full_date.group(1)), int(full_date.group(2)), int(full_date.group(3))).isoformat()
        except ValueError:
            return default_seen_date
    return default_seen_date


def parse_iso_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def parse_ithome_published_at(label: str, *, window_end: str) -> str | None:
    text = clean_text(label)
    if not text:
        return None
    try:
        base = parse_iso_datetime(window_end)
    except ValueError:
        return None

    def build_at(target_date: date, hour: int = 0, minute: int = 0) -> str:
        return datetime(
            target_date.year,
            target_date.month,
            target_date.day,
            hour,
            minute,
            tzinfo=base.tzinfo,
        ).isoformat(timespec="seconds")

    time_match = re.search(r"(\d{1,2}):(\d{2})", text)
    hour = int(time_match.group(1)) if time_match else 0
    minute = int(time_match.group(2)) if time_match else 0

    if "刚刚" in text:
        return base.isoformat(timespec="seconds")
    minutes = re.search(r"(\d+)\s*分钟前", text)
    if minutes:
        return (base - timedelta(minutes=int(minutes.group(1)))).isoformat(timespec="seconds")
    hours = re.search(r"(\d+)\s*小时前", text)
    if hours:
        return (base - timedelta(hours=int(hours.group(1)))).isoformat(timespec="seconds")
    if "今日" in text:
        return build_at(base.date(), hour, minute)
    if "昨日" in text:
        return build_at(base.date() - timedelta(days=1), hour, minute)

    full_date = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})日?", text)
    if full_date:
        return build_at(
            date(int(full_date.group(1)), int(full_date.group(2)), int(full_date.group(3))),
            hour,
            minute,
        )

    month_day = re.search(r"(\d{1,2})月(\d{1,2})日", text)
    if month_day:
        month = int(month_day.group(1))
        day = int(month_day.group(2))
        candidate = date(base.year, month, day)
        if candidate > base.date():
            candidate = date(base.year - 1, month, day)
        return build_at(candidate, hour, minute)

    return None


def row_in_collect_window(row: dict[str, Any], *, window_start: str, window_end: str) -> bool:
    published_at = row.get("published_at")
    if not published_at:
        return True
    return str(window_start) < str(published_at) <= str(window_end)


def ithome_search_results_region(html: str) -> str:
    list_start = re.search(r'<div\b[^>]*\bid\s*=\s*["\']list["\'][^>]*>', html, flags=re.I)
    if not list_start:
        return ""
    region = html[list_start.start() :]
    right_column = re.search(r'<div\b[^>]*\bclass\s*=\s*["\'][^"\']*\bfr\b[^"\']*\bfx\b[^"\']*["\']', region, flags=re.I)
    if right_column:
        region = region[: right_column.start()]
    return region


def parse_ithome_brand_search_page_bs4(
    html: str,
    base_url: str,
    *,
    brand: str,
    source_type: str,
    source_name: str,
    seen_date: str | None = None,
    collected_at: str | None = None,
    window_end: str | None = None,
) -> list[dict[str, Any]]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    rows: list[dict[str, Any]] = []
    for item in soup.select("#list .fl ul.bl li"):
        anchor = item.select_one("a.title[href]")
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip()
        title = clean_text(str(anchor.get("title") or anchor.get_text(" ", strip=True)))
        absolute = canonical_url(urljoin(base_url, href))
        if not title or not is_ithome_news_url(absolute):
            continue
        state = item.select_one(".state")
        state_text = state.get_text(" ", strip=True) if state is not None else ""
        published_at = parse_ithome_published_at(state_text, window_end=window_end) if window_end else None
        rows.append(
            make_news_row(
                brand=brand,
                source_type=source_type,
                source_name=source_name,
                title=title,
                url=absolute,
                seen_date=ithome_search_seen_date(state_text, seen_date),
                collected_at=collected_at,
                published_at=published_at,
            )
        )
    return dedupe_news_rows(rows)


def dedupe_ithome_candidates(candidates: list[IthomeSearchCandidate]) -> list[IthomeSearchCandidate]:
    deduped: list[IthomeSearchCandidate] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = canonical_url(candidate.url)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(candidate)
    return deduped


def parse_ithome_search_candidates_bs4(
    html: str,
    base_url: str,
    *,
    seen_date: str | None = None,
    window_end: str | None = None,
) -> list[IthomeSearchCandidate]:
    if BeautifulSoup is None:
        return []
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[IthomeSearchCandidate] = []
    for item in soup.select("#list .fl ul.bl li"):
        anchor = item.select_one("a.title[href]")
        if anchor is None:
            continue
        href = str(anchor.get("href") or "").strip()
        title = clean_text(str(anchor.get("title") or anchor.get_text(" ", strip=True)))
        absolute = canonical_url(urljoin(base_url, href))
        if not title or not is_ithome_news_url(absolute):
            continue
        state = item.select_one(".state")
        state_text = clean_text(state.get_text(" ", strip=True)) if state is not None else ""
        candidates.append(
            IthomeSearchCandidate(
                title=title,
                url=absolute,
                state_text=state_text,
                seen_date=ithome_search_seen_date(state_text, seen_date),
                published_at=parse_ithome_published_at(state_text, window_end=window_end) if window_end else None,
            )
        )
    return dedupe_ithome_candidates(candidates)


def parse_ithome_search_candidates(
    html: str,
    base_url: str,
    *,
    seen_date: str | None = None,
    window_end: str | None = None,
) -> list[IthomeSearchCandidate]:
    bs4_candidates = parse_ithome_search_candidates_bs4(
        html,
        base_url,
        seen_date=seen_date,
        window_end=window_end,
    )
    if bs4_candidates:
        return bs4_candidates

    region = ithome_search_results_region(html)
    if not region:
        return []
    candidates: list[IthomeSearchCandidate] = []
    for block in re.findall(r"<li\b.*?</li>", region, flags=re.S | re.I):
        anchor = re.search(
            r'(<a\b[^>]*\bclass\s*=\s*["\'][^"\']*\btitle\b[^"\']*["\'][^>]*>)(.*?)</a>',
            block,
            flags=re.S | re.I,
        )
        if not anchor:
            continue
        tag = anchor.group(1)
        href = html_attr(tag, "href").strip()
        title = clean_text(html_attr(tag, "title") or html_fragment_text(anchor.group(2)))
        absolute = canonical_url(urljoin(base_url, href))
        if not title or not is_ithome_news_url(absolute):
            continue
        state = re.search(
            r'<span\b[^>]*\bclass\s*=\s*["\'][^"\']*\bstate\b[^"\']*["\'][^>]*>(.*?)</span>',
            block,
            flags=re.S | re.I,
        )
        state_text = html_fragment_text(state.group(1)) if state else ""
        candidates.append(
            IthomeSearchCandidate(
                title=title,
                url=absolute,
                state_text=state_text,
                seen_date=ithome_search_seen_date(state_text, seen_date),
                published_at=parse_ithome_published_at(state_text, window_end=window_end) if window_end else None,
            )
        )
    return dedupe_ithome_candidates(candidates)


def parse_ithome_link_candidates(
    html: str,
    base_url: str,
    *,
    seen_date: str | None = None,
    window_end: str | None = None,
) -> list[IthomeSearchCandidate]:
    parser = parse_html(html)
    candidates: list[IthomeSearchCandidate] = []
    for link in parser.links:
        title = clean_text(f"{link.text} {link.title}").strip()
        href = (link.href or "").strip()
        if not title or not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        absolute = canonical_url(urljoin(base_url, href))
        if not is_ithome_news_url(absolute):
            continue
        candidates.append(
            IthomeSearchCandidate(
                title=title,
                url=absolute,
                seen_date=seen_date,
                published_at=f"{seen_date}T00:00:00+00:00" if seen_date and window_end else None,
            )
        )
    return dedupe_ithome_candidates(candidates)


def row_from_ithome_candidate(
    candidate: IthomeSearchCandidate,
    *,
    source: NewsSource,
    seen_date: str,
    collected_at: str,
) -> dict[str, Any] | None:
    title = clean_text(candidate.title)
    url = canonical_url(candidate.url)
    if not title or not is_ithome_news_url(url):
        return None
    return make_news_row(
        brand=source.brand,
        source_type=source.source_type,
        source_name=source.source_name,
        title=title,
        url=url,
        seen_date=candidate.seen_date or seen_date,
        collected_at=collected_at,
        published_at=candidate.published_at,
    )


def enrich_ithome_candidate_from_detail(
    candidate: IthomeSearchCandidate,
    detail_html: str,
    *,
    source: NewsSource,
    seen_date: str,
    collected_at: str,
    window_end: str | None = None,
) -> dict[str, Any] | None:
    detail_url = html_canonical_url(detail_html, candidate.url)
    if is_ithome_detail_abnormal(detail_html):
        return row_from_ithome_candidate(
            candidate,
            source=source,
            seen_date=seen_date,
            collected_at=collected_at,
        )

    detail_title = ithome_detail_title_text(detail_html)
    title = detail_title or candidate.title
    if not title:
        return None

    published_at = ithome_detail_published_at(detail_html, window_end=window_end) or candidate.published_at
    row_seen_date = candidate.seen_date or seen_date
    if published_at:
        row_seen_date = published_at[:10]

    return make_news_row(
        brand=source.brand,
        source_type=source.source_type,
        source_name=source.source_name,
        title=title,
        url=detail_url,
        seen_date=row_seen_date,
        collected_at=collected_at,
        published_at=published_at,
    )


def parse_ithome_brand_search_page(
    html: str,
    base_url: str,
    *,
    brand: str,
    source_type: str,
    source_name: str,
    seen_date: str | None = None,
    collected_at: str | None = None,
    window_end: str | None = None,
) -> list[dict[str, Any]]:
    candidates = parse_ithome_search_candidates(
        html,
        base_url,
        seen_date=seen_date,
        window_end=window_end,
    )
    source = NewsSource(brand=brand, source_type=source_type, source_name=source_name)
    rows: list[dict[str, Any]] = []
    for candidate in candidates:
        row = row_from_ithome_candidate(
            candidate,
            source=source,
            seen_date=seen_date or (collected_at or utc_now())[:10],
            collected_at=collected_at or utc_now(),
        )
        if row is None:
            continue
        rows.append(row)
    return dedupe_news_rows(rows)


def brand_from_phone_news_title(title: str) -> str | None:
    normalized = title.lower()
    if any(token in title for token in ("中兴", "努比亚", "红魔")):
        return "ZTE"
    if "摩托罗拉" in title:
        return "MOTOROLA"
    if "小米" in title or "redmi" in normalized or "poco" in normalized:
        return "XIAOMI"
    if "三星" in title:
        return "SAMSUNG"
    if "oppo" in normalized:
        return "OPPO"
    if "荣耀" in title:
        return "HONOR"
    if "vivo" in normalized or "iqoo" in normalized:
        return "VIVO"
    return None


def link_context_contains_seen_date(html: str, href: str, seen_date: str) -> bool:
    for tag in ("article", "li", "section", "div"):
        pattern = rf"<{tag}\b[^>]*>.*?</{tag}>"
        for match in re.finditer(pattern, html, flags=re.S | re.I):
            block = match.group(0)
            if href not in block:
                continue
            return seen_date in block
    position = html.find(href)
    if position >= 0:
        context = html[max(0, position - 120) : position + 120]
        if seen_date in context:
            return True
    return False


def parse_ithome_phone_today_html(
    html: str,
    base_url: str,
    *,
    source_name: str,
    seen_date: str,
    collected_at: str | None = None,
    window_end: str | None = None,
) -> list[dict[str, Any]]:
    parser = parse_html(html)
    rows: list[dict[str, Any]] = []
    for link in parser.links:
        title = clean_text(f"{link.text} {link.title}")
        href = (link.href or "").strip()
        absolute = canonical_url(urljoin(base_url, href))
        if not title or not is_ithome_news_url(absolute):
            continue
        if seen_date in html and not link_context_contains_seen_date(html, href, seen_date):
            continue
        brand = brand_from_phone_news_title(title) or GENERAL_NEWS_BRAND
        rows.append(
            make_news_row(
                brand=brand,
                source_type="ithome_phone_today",
                source_name=source_name,
                title=title,
                url=absolute,
                seen_date=seen_date,
                collected_at=collected_at,
                published_at=f"{seen_date}T00:00:00+00:00" if window_end else None,
            )
        )
    return dedupe_news_rows(rows)


def should_render_source(source: NewsSource, render_mode: RenderMode) -> bool:
    if render_mode in {"always", "playwright"}:
        return True
    if render_mode == "never":
        return False
    return bool(source.render)


def default_fetcher(
    url: str,
    *,
    render: bool = False,
    timeout: int = 20,
    allow_render_fallback: bool = True,
) -> tuple[str, dict[str, int]]:
    stats = {"rendered": 0, "render_errors": 0, "fallbacks": 0}
    if render:
        rendered_html = fetch_rendered_html(url, timeout=timeout)
        if rendered_html:
            stats["rendered"] = 1
            return rendered_html, stats
        stats["render_errors"] = 1
        if not allow_render_fallback:
            raise RuntimeError(f"Playwright render failed: {url}")
        stats["fallbacks"] = 1
    if is_ithome_search_url(url):
        return fetch_ithome_search_html(url, timeout=timeout), stats
    return fetch_html(url, timeout=timeout), stats


def default_ithome_search_browser_fetcher(keyword: str, *, timeout: int = 20) -> tuple[str, dict[str, int]] | None:
    html = fetch_ithome_search_html_like_user(keyword, timeout=timeout)
    if not html:
        return None
    return html, {"rendered": 1, "render_errors": 0, "fallbacks": 1}


def fetcher_accepts_render_fallback(fetcher: Fetcher) -> bool:
    try:
        parameters = signature(fetcher).parameters.values()
    except (TypeError, ValueError):
        return True
    return any(
        parameter.kind == Parameter.VAR_KEYWORD or parameter.name == "allow_render_fallback"
        for parameter in parameters
    )


def call_fetcher(
    fetcher: Fetcher,
    url: str,
    *,
    render: bool,
    timeout: int,
    allow_render_fallback: bool,
) -> FetchResult:
    if fetcher_accepts_render_fallback(fetcher):
        return fetcher(
            url,
            render=render,
            timeout=timeout,
            allow_render_fallback=allow_render_fallback,
        )
    return fetcher(url, render=render, timeout=timeout)


def source_matches(source: NewsSource, *, brand: str | None, source_type: str | None) -> bool:
    if brand and source.brand not in {brand.upper(), "ALL"}:
        return False
    if source_type and source.source_type != source_type.lower():
        return False
    return True


def ordered_news_sources_for_collection(config: NewsConfig, *, brand: str | None, source_type: str | None) -> list[NewsSource]:
    sources = [source for source in config.sources if source_matches(source, brand=brand, source_type=source_type)]
    if source_type:
        return sources
    return sorted(sources, key=lambda source: 0 if source.source_type == "ithome_phone_today" else 1)


def urls_for_source(source: NewsSource) -> list[str]:
    if source.source_type == "ithome_brand_search":
        keywords = source.search_keywords or ()
        if keywords:
            return [IT_HOME_TAG_URL.format(keyword=quote(keyword)) for keyword in keywords]
        return list(source.start_urls)
    return list(source.start_urls)


def brand_mobile_fallback_terms(config: NewsConfig, source: NewsSource) -> list[str]:
    terms = [*config.brand_keywords.get(source.brand.upper(), ()), *source.search_keywords]
    if source.brand and source.brand.upper() != GENERAL_NEWS_BRAND:
        terms.append(source.brand)
    seen: set[str] = set()
    deduped: list[str] = []
    for term in terms:
        normalized = clean_text(str(term))
        if normalized.endswith("手机"):
            terms.append(normalized[: -len("手机")])
        key = normalized.casefold()
        if not normalized or key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
    return deduped


def mobile_fallback_rows_for_brand(
    mobile_rows: list[dict[str, Any]],
    *,
    config: NewsConfig,
    source: NewsSource,
) -> list[dict[str, Any]]:
    terms = brand_mobile_fallback_terms(config, source)
    if not terms:
        return []
    lowered_terms = [term.casefold() for term in terms]
    rows: list[dict[str, Any]] = []
    for row in mobile_rows:
        title = clean_text(str(row.get("title") or ""))
        if not any(term in title.casefold() for term in lowered_terms):
            continue
        fallback_row = dict(row)
        fallback_row["brand"] = source.brand.upper()
        fallback_row["source_type"] = source.source_type.lower()
        fallback_row["source_name"] = source.source_name
        fallback_row["last_error"] = MOBILE_KEYWORD_FALLBACK_ERROR
        rows.append(fallback_row)
    return dedupe_news_rows(rows)


def brand_tag_failure_row(
    source: NewsSource,
    url: str,
    *,
    seen_date: str,
    collected_at: str,
) -> dict[str, Any]:
    return make_news_row(
        brand=source.brand.upper(),
        source_type=source.source_type.lower(),
        source_name=source.source_name,
        title=f"{source.source_name} 当日爬取失败",
        url=url,
        seen_date=seen_date,
        collected_at=collected_at,
    ) | {"last_error": MOBILE_KEYWORD_FALLBACK_ERROR}


def rows_from_source_html(
    source: NewsSource,
    html: str,
    url: str,
    *,
    seen_date: str,
    collected_at: str,
    window_end: str | None = None,
) -> list[dict[str, Any]]:
    if source.source_type == "ithome_phone_today":
        return parse_ithome_phone_today_html(
            html,
            url,
            source_name=source.source_name,
            seen_date=seen_date,
            collected_at=collected_at,
            window_end=window_end,
        )
    return parse_news_links_from_html(
        html,
        url,
        brand=source.brand,
        source_type=source.source_type,
        source_name=source.source_name,
        seen_date=seen_date,
        collected_at=collected_at,
        window_end=window_end,
    )


def call_ithome_detail_fetcher(fetcher: Fetcher, url: str, *, timeout: int) -> FetchResult:
    return call_fetcher(
        fetcher,
        url,
        render=False,
        timeout=timeout,
        allow_render_fallback=False,
    )


def collect_ithome_candidate_rows(
    source: NewsSource,
    candidates: list[IthomeSearchCandidate],
    *,
    detail_fetcher: Fetcher,
    timeout: int,
    seen_date: str,
    collected_at: str,
    window_end: str | None,
    counts: dict[str, int],
    detail_sleeper: Callable[[float], None],
    detail_random_uniform: Callable[[float, float], float],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates):
        if index > 0:
            delay = detail_random_uniform(*IT_HOME_DETAIL_DELAY_RANGE)
            detail_sleeper(delay)
        try:
            detail_result = call_ithome_detail_fetcher(detail_fetcher, candidate.url, timeout=timeout)
        except Exception as exc:
            counts["detail_errors"] += 1
            print(
                f"[WARN] news detail failed: {source.source_name} {candidate.url} ({type(exc).__name__}: {exc})",
                flush=True,
            )
            row = row_from_ithome_candidate(
                candidate,
                source=source,
                seen_date=seen_date,
                collected_at=collected_at,
            )
            if row is not None:
                rows.append(row)
            continue

        if isinstance(detail_result, tuple):
            detail_html, detail_stats = detail_result
            for key in ("rendered", "render_errors", "fallbacks"):
                counts[key] += int(detail_stats.get(key, 0))
        else:
            detail_html = detail_result

        counts["detail_fetched"] += 1
        if is_ithome_detail_abnormal(detail_html):
            counts["detail_errors"] += 1
            print(
                f"[WARN] news detail abnormal: {source.source_name} {candidate.url}",
                flush=True,
            )
        row = enrich_ithome_candidate_from_detail(
            candidate,
            detail_html,
            source=source,
            seen_date=seen_date,
            collected_at=collected_at,
            window_end=window_end,
        )
        if row is not None:
            rows.append(row)
    return dedupe_news_rows(rows)


def collect_news_sources_to_db(
    conn,
    config: NewsConfig,
    *,
    brand: str | None = None,
    source_type: str | None = None,
    timeout: int = 20,
    render_mode: RenderMode = "config",
    allow_render_fallback: bool = True,
    fetcher: Fetcher | None = None,
    ithome_search_browser_fetcher: BrowserSearchFetcher | None = None,
    now: str | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    collect_run_id: int | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    random_uniform: Callable[[float, float], float] = random.uniform,
    detail_fetcher: Fetcher | None = None,
    detail_sleeper: Callable[[float], None] = time.sleep,
    detail_random_uniform: Callable[[float, float], float] = random.uniform,
) -> dict[str, int]:
    collected_at = now or utc_now()
    effective_window_end = window_end or collected_at
    seen_date = collected_at[:10]
    active_fetcher = fetcher or default_fetcher
    active_detail_fetcher = detail_fetcher or active_fetcher
    active_ithome_search_browser_fetcher = ithome_search_browser_fetcher
    if active_ithome_search_browser_fetcher is None and active_fetcher is default_fetcher:
        active_ithome_search_browser_fetcher = default_ithome_search_browser_fetcher
    counts = {
        "sources": 0,
        "fetched": 0,
        "parsed": 0,
        "inserted": 0,
        "errors": 0,
        "rendered": 0,
        "render_errors": 0,
        "fallbacks": 0,
        "detail_fetched": 0,
        "detail_errors": 0,
    }
    ithome_search_request_count = 0
    mobile_phone_rows: list[dict[str, Any]] = []

    for source in ordered_news_sources_for_collection(config, brand=brand, source_type=source_type):
        counts["sources"] += 1
        source_rows: list[dict[str, Any]] = []
        for url in urls_for_source(source):
            if is_ithome_search_url(url):
                ithome_search_request_count += 1
                throttle_ithome_search_request(
                    ithome_search_request_count,
                    sleeper=sleeper,
                    random_uniform=random_uniform,
                )
            try:
                fetch_result = call_fetcher(
                    active_fetcher,
                    url,
                    render=should_render_source(source, render_mode),
                    timeout=timeout,
                    allow_render_fallback=allow_render_fallback,
                )
            except Exception as exc:
                counts["errors"] += 1
                print(f"[WARN] news source failed: {source.source_name} {url} ({type(exc).__name__}: {exc})", flush=True)
                if source.source_type == "ithome_brand_search" and mobile_phone_rows:
                    fallback_rows = mobile_fallback_rows_for_brand(
                        mobile_phone_rows,
                        config=config,
                        source=source,
                    )
                    if fallback_rows:
                        counts["fallbacks"] += 1
                        source_rows.extend(fallback_rows)
                    else:
                        source_rows.append(brand_tag_failure_row(source, url, seen_date=seen_date, collected_at=collected_at))
                elif source.source_type == "ithome_brand_search":
                    source_rows.append(brand_tag_failure_row(source, url, seen_date=seen_date, collected_at=collected_at))
                continue
            if isinstance(fetch_result, tuple):
                html, fetch_stats = fetch_result
                for key in ("rendered", "render_errors", "fallbacks"):
                    counts[key] += int(fetch_stats.get(key, 0))
            else:
                html = fetch_result
            counts["fetched"] += 1
            ithome_brand_search = source.source_type == "ithome_brand_search"
            search_candidates: list[IthomeSearchCandidate] = []
            if ithome_brand_search:
                search_candidates = parse_ithome_search_candidates(
                    html,
                    url,
                    seen_date=seen_date,
                    window_end=effective_window_end,
                )
                if not search_candidates:
                    search_candidates = parse_ithome_link_candidates(
                        html,
                        url,
                        seen_date=seen_date,
                        window_end=effective_window_end,
                    )
                url_rows = []
            else:
                url_rows = rows_from_source_html(
                    source,
                    html,
                    url,
                    seen_date=seen_date,
                    collected_at=collected_at,
                    window_end=effective_window_end,
                )
                if source.source_type == "ithome_phone_today":
                    mobile_phone_rows.extend(url_rows)
            if (
                ithome_brand_search
                and not search_candidates
                and allow_render_fallback
                and not should_render_source(source, render_mode)
                and is_ithome_search_url(url)
                and is_ithome_blocked_or_error(html)
            ):
                keyword = ithome_search_keyword_from_url(url)
                if keyword and active_ithome_search_browser_fetcher is not None:
                    try:
                        browser_fallback_result = active_ithome_search_browser_fetcher(
                            keyword,
                            timeout=timeout,
                        )
                    except Exception as exc:
                        counts["errors"] += 1
                        print(
                            f"[WARN] news source browser search fallback failed: {source.source_name} {url} ({type(exc).__name__}: {exc})",
                            flush=True,
                        )
                    else:
                        browser_fallback_html = ""
                        if isinstance(browser_fallback_result, tuple):
                            browser_fallback_html, browser_fallback_stats = browser_fallback_result
                            fallback_counted = False
                            for key in ("rendered", "render_errors", "fallbacks"):
                                value = int(browser_fallback_stats.get(key, 0))
                                counts[key] += value
                                if key == "fallbacks" and value:
                                    fallback_counted = True
                            if not fallback_counted:
                                counts["fallbacks"] += 1
                        elif browser_fallback_result:
                            browser_fallback_html = browser_fallback_result
                            counts["rendered"] += 1
                            counts["fallbacks"] += 1
                        else:
                            counts["render_errors"] += 1

                        if browser_fallback_html:
                            browser_fallback_candidates = parse_ithome_search_candidates(
                                browser_fallback_html,
                                url,
                                seen_date=seen_date,
                                window_end=effective_window_end,
                            )
                            if not browser_fallback_candidates:
                                browser_fallback_candidates = parse_ithome_link_candidates(
                                    browser_fallback_html,
                                    url,
                                    seen_date=seen_date,
                                    window_end=effective_window_end,
                                )
                            if browser_fallback_candidates:
                                search_candidates = browser_fallback_candidates

                if search_candidates:
                    source_rows.extend(
                        collect_ithome_candidate_rows(
                            source,
                            search_candidates,
                            detail_fetcher=active_detail_fetcher,
                            timeout=timeout,
                            seen_date=seen_date,
                            collected_at=collected_at,
                            window_end=effective_window_end,
                            counts=counts,
                            detail_sleeper=detail_sleeper,
                            detail_random_uniform=detail_random_uniform,
                        )
                    )
                    continue

                try:
                    fallback_result = call_fetcher(
                        active_fetcher,
                        url,
                        render=True,
                        timeout=timeout,
                        allow_render_fallback=allow_render_fallback,
                    )
                except Exception as exc:
                    counts["errors"] += 1
                    print(
                        f"[WARN] news source render fallback failed: {source.source_name} {url} ({type(exc).__name__}: {exc})",
                        flush=True,
                    )
                else:
                    if isinstance(fallback_result, tuple):
                        fallback_html, fallback_stats = fallback_result
                        fallback_counted = False
                        for key in ("rendered", "render_errors", "fallbacks"):
                            value = int(fallback_stats.get(key, 0))
                            counts[key] += value
                            if key == "fallbacks" and value:
                                fallback_counted = True
                        if not fallback_counted:
                            counts["fallbacks"] += 1
                    else:
                        fallback_html = fallback_result
                        counts["fallbacks"] += 1
                    fallback_candidates = parse_ithome_search_candidates(
                        fallback_html,
                        url,
                        seen_date=seen_date,
                        window_end=effective_window_end,
                    )
                    if not fallback_candidates:
                        fallback_candidates = parse_ithome_link_candidates(
                            fallback_html,
                            url,
                            seen_date=seen_date,
                            window_end=effective_window_end,
                        )
                    if fallback_candidates:
                        search_candidates = fallback_candidates
                    elif is_ithome_blocked_or_error(fallback_html):
                        counts["errors"] += 1
                        print(
                            f"[WARN] news source blocked or abnormal after fallback: {source.source_name} {url}",
                            flush=True,
                        )
            if ithome_brand_search:
                if search_candidates:
                    url_rows = collect_ithome_candidate_rows(
                        source,
                        search_candidates,
                        detail_fetcher=active_detail_fetcher,
                        timeout=timeout,
                        seen_date=seen_date,
                        collected_at=collected_at,
                        window_end=effective_window_end,
                        counts=counts,
                        detail_sleeper=detail_sleeper,
                        detail_random_uniform=detail_random_uniform,
                    )
                elif mobile_phone_rows:
                    fallback_rows = mobile_fallback_rows_for_brand(
                        mobile_phone_rows,
                        config=config,
                        source=source,
                    )
                    if fallback_rows:
                        counts["errors"] += 1
                        counts["fallbacks"] += 1
                        url_rows = fallback_rows
                    else:
                        counts["errors"] += 1
                        url_rows = [brand_tag_failure_row(source, url, seen_date=seen_date, collected_at=collected_at)]
                else:
                    counts["errors"] += 1
                    url_rows = [brand_tag_failure_row(source, url, seen_date=seen_date, collected_at=collected_at)]
            source_rows.extend(url_rows)
        recent_counts: dict[tuple[str, str], int] = {}
        for row in dedupe_news_rows(source_rows):
            row["collect_run_id"] = collect_run_id
            row["collect_window_start"] = window_start
            row["collect_window_end"] = effective_window_end
            if window_start and effective_window_end and row.get("published_at"):
                if not row_in_collect_window(row, window_start=window_start, window_end=effective_window_end):
                    existing = db.find_news_item_by_brand_source_url(
                        conn,
                        row["brand"],
                        row["source_type"],
                        row["url"],
                    )
                    if existing:
                        continue
                    count_key = (str(row["brand"]).upper(), str(row["source_type"]).lower())
                    if count_key not in recent_counts:
                        recent_counts[count_key] = db.count_recent_news_for_brand(
                            conn,
                            row["brand"],
                            row["source_type"],
                        )
                    if recent_counts[count_key] >= int(config.fallback_limit):
                        continue
                    recent_counts[count_key] += 1
            db.upsert_news_item(conn, row)
            counts["inserted"] += 1
        counts["parsed"] += len(source_rows)
    return counts
