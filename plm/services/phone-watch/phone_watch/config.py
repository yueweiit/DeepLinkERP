from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_CONFIG = Path("config/sources.json")
DEFAULT_NEWS_CONFIG = Path("config/news_sources.json")
NEWS_SOURCE_TYPES = {"ithome_brand_search", "ithome_phone_today"}
REQUIRED_NEWS_BRANDS = {"ZTE", "MOTOROLA", "XIAOMI", "SAMSUNG", "OPPO", "HONOR", "VIVO", "HUAWEI"}


@dataclass(frozen=True)
class Source:
    brand: str
    country: str
    country_name: str
    name: str
    start_urls: tuple[str, ...]
    reference_only: bool = False
    force_new_label: bool = False
    render: bool = False


@dataclass(frozen=True)
class NewsSource:
    brand: str
    source_type: str
    source_name: str
    start_urls: tuple[str, ...] = ()
    search_keywords: tuple[str, ...] = ()
    render: bool = False


@dataclass(frozen=True)
class NewsConfig:
    retention_days: int
    fallback_limit: int
    brand_keywords: dict[str, tuple[str, ...]]
    sources: tuple[NewsSource, ...]


def load_sources(path: str | Path = DEFAULT_CONFIG) -> list[Source]:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    sources: list[Source] = []
    for item in data.get("sources", []):
        sources.append(
            Source(
                brand=str(item["brand"]).upper(),
                country=str(item["country"]).upper(),
                country_name=str(item.get("country_name") or item["country"]),
                name=str(item["name"]),
                start_urls=tuple(item.get("start_urls", [])),
                reference_only=bool(item.get("reference_only", False)),
                force_new_label=bool(item.get("force_new_label", False)),
                render=bool(item.get("render", False)),
            )
        )
    return sources


def load_news_config(path: str | Path = DEFAULT_NEWS_CONFIG) -> NewsConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    retention_days = int(data.get("retention_days", 7))
    fallback_limit = int(data.get("fallback_limit", 3))

    brand_keywords = {
        str(brand).upper(): tuple(str(keyword) for keyword in keywords)
        for brand, keywords in data.get("brand_keywords", {}).items()
    }
    missing_brands = sorted(REQUIRED_NEWS_BRANDS - set(brand_keywords))
    if missing_brands:
        raise ValueError(f"brand_keywords missing required brands: {', '.join(missing_brands)}")

    sources: list[NewsSource] = []
    for item in data.get("sources", []):
        source_type = str(item["source_type"]).lower()
        if source_type not in NEWS_SOURCE_TYPES:
            raise ValueError(f"Unsupported news source_type: {source_type}")
        sources.append(
            NewsSource(
                brand=str(item["brand"]).upper(),
                source_type=source_type,
                source_name=str(item["source_name"]),
                start_urls=tuple(str(url) for url in item.get("start_urls", [])),
                search_keywords=tuple(str(keyword) for keyword in item.get("search_keywords", [])),
                render=bool(item.get("render", False)),
            )
        )

    return NewsConfig(
        retention_days=retention_days,
        fallback_limit=fallback_limit,
        brand_keywords=brand_keywords,
        sources=tuple(sources),
    )


def select_sources(
    sources: Iterable[Source],
    *,
    brand: str | None = None,
    country: str | None = None,
    include_reference: bool = False,
) -> list[Source]:
    selected: list[Source] = []
    brand_filter = brand.upper() if brand else None
    country_filter = country.upper() if country else None

    for source in sources:
        if source.reference_only and not include_reference:
            continue
        if brand_filter and source.brand != brand_filter:
            continue
        if country_filter and source.country != country_filter:
            continue
        selected.append(source)
    return selected
