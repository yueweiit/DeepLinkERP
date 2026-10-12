from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timedelta
from html import unescape
from typing import Any

from . import db

try:
    import pg8000.dbapi as pg8000
except ImportError:  # pragma: no cover - optional only when PG library filtering is enabled
    pg8000 = None


ACCESSORY_WORDS = {
    "accessory",
    "accessories",
    "accesorio",
    "accesorios",
    "case",
    "cover",
    "funda",
    "protector",
    "screen protector",
    "tempered glass",
    "charger",
    "cargador",
    "cable",
    "usb",
    "braided",
    "bundle",
    "combo",
    "kit",
    "refurbished",
    "renewed",
    "renovado",
    "reacondicionado",
    "seminuevo",
    "usado",
    "mica",
    "cristal",
    "vidrio",
    "bateria",
    "battery",
    "powerbank",
    "power bank",
    "strap",
    "correa",
    "soporte",
    "watch",
    "buds",
    "earbuds",
    "tablet",
    "tab",
    "pad",
    "laptop",
    "notebook",
    "monitor",
    "tv",
    "router",
    "wearable",
    "reloj",
    "auriculares",
    "耳机",
    "手表",
    "平板",
    "保护壳",
}

NON_PHONE_CONTEXT_PATTERNS = [
    r"\baccessor(?:y|ies)\b",
    r"\baccesorios?\b",
    r"\bcase\b",
    r"\bcover\b",
    r"\bfunda\b",
    r"\bprotector\b",
    r"\bscreen\s+protector\b",
    r"\btempered\s+glass\b",
    r"\bcharger\b",
    r"\bcargador\b",
    r"\bcable\b",
    r"\busb\b",
    r"\bbraided\b",
    r"\bbundle\b",
    r"\bcombo\b",
    r"\bkit\b",
    r"\brefurbished\b",
    r"\brenewed\b",
    r"\brenovado\b",
    r"\breacondicionado\b",
    r"\bseminuevo\b",
    r"\busado\b",
    r"\bmica\b",
    r"\bcristal\b",
    r"\bvidrio\b",
    r"\bbater[ií]a\b",
    r"\bbattery\b",
    r"\bpower\s?bank\b",
    r"\bstrap\b",
    r"\bcorrea\b",
    r"\bsoporte\b",
    r"\bwatch\b",
    r"\bbuds?\b",
    r"\bearbuds?\b",
    r"\btablet\b",
    r"\btablets\b",
    r"\btab\b",
    r"\bpad\b",
    r"\blaptop\b",
    r"\bnotebook\b",
    r"\bmonitor\b",
    r"\btv\b",
    r"\brouter\b",
    r"\bwearable\b",
    r"\baudio\b",
    r"\breloj\b",
    r"\bauriculares\b",
    r"耳机",
    r"手表",
    r"平板",
    r"保护壳",
    r"充电器",
    r"케이스",
    r"버즈",
    r"워치",
    r"탭",
]

NEW_LABEL_PATTERNS = [
    r"\bnuevo\b",
    r"\bnueva\b",
    r"\bnew\b",
    r"lanzamiento",
    r"新品",
    r"新机",
    r"首发",
    r"发布会",
    r"预约",
    r"预售",
    r"敬请期待",
    r"即将发布",
    r"即将推出",
    r"即将开售",
    r"coming soon",
    r"reci[eé]n",
    r"新款",
    r"新品",
    r"新机",
    r"首发",
    r"上市",
    r"신제품",
    r"출시",
]

BRAND_PATTERNS: dict[str, list[str]] = {
    "MOTOROLA": [
        r"(?:motorola\s+)?edge\s+\d{2,3}(?:\s*(?:pro|ultra|neo|fusion|plus|\+|lite|5g))*",
        r"moto\s+g\d{1,3}[a-z]?(?:\s*(?:power|play|stylus|plus|\+|5g|pro))*",
        r"(?:motorola\s+)?razr\s+\d{2,4}(?:\s*(?:ultra|plus|\+|5g))*",
    ],
    "OPPO": [
        r"oppo\s+find\s+[nx]\d{1,2}[a-z]?(?:\s*(?:pro|ultra|mini|flip|5g))*",
        r"oppo\s+reno\s*\d{1,2}[a-z]?(?:\s*(?:pro|plus|\+|5g))*",
        r"oppo\s+a\d{1,3}[a-z]?(?:\s*(?:pro|max|gt|plus|\+|5g))*",
        r"oppo\s+k\d{1,3}[a-z]?(?:\s*(?:turbo|pro|max|plus|\+|5g))*",
    ],
    "VIVO": [
        r"vivo\s+x\s*(?:fold|flip)?\s*\d{1,3}[a-z]?(?:\s*(?:pro|ultra|plus|\+|mini|5g))*",
        r"vivo\s+v\d{1,3}[a-z]?(?:\s*(?:pro|lite|plus|\+|fe|5g))*",
        r"vivo\s+y\d{1,3}[a-z]?(?:\s*(?:pro|lite|plus|\+|5g))*",
        r"vivo\s+s\d{1,3}[a-z]?(?:\s*(?:pro|lite|plus|\+|元气版|5g))*",
        r"iqoo\s+\d{1,2}[a-z]?(?:\s*(?:pro|ultra|plus|\+|neo|t|5g))*",
    ],
    "HONOR": [
        r"honor\s+magic\s*(?:v|vs)?\s*\d{1,3}[a-z]?(?:\s*(?:pro|ultra|lite|rsr|5g))*",
        r"honor\s+x\d{1,3}[a-z]?(?:\s*(?:pro|plus|\+|5g))*",
        r"honor\s+play\s*\d{1,3}[a-z]?(?:\s*(?:pro|plus|\+|5g))*",
        r"honor\s+\d{2,3}[a-z]?(?:\s*(?:pro|smart|lite|plus|\+|5g))*",
    ],
    "XIAOMI": [
        r"小米\s*\d{1,2}[a-z]?(?:\s*(?:pro|max|ultra|lite|plus|\+|5g|e|t|s))*",
        r"xiaomi\s+\d{1,2}[a-z]?(?:\s*(?:pro|max|ultra|lite|plus|\+|5g|e|t|s))*",
        r"xiaomi\s+\d{1,2}\s+max(?:\s*(?:pro|ultra|lite|plus|\+|5g|e|t|s))*",
        r"小米\s*\d{1,2}\s*max(?:\s*(?:pro|ultra|lite|plus|\+|5g|e|t|s))*",
        r"xiaomi\s+(?:mix|civi)\s*[a-z0-9]{1,8}(?:\s*(?:pro|max|ultra|lite|plus|\+|5g))*",
        r"redmi\s+note\s+\d{1,2}[a-z]?(?:\s*(?:pro|max|plus|\+|5g))*",
        r"redmi\s+k\d{1,3}[a-z]?(?:\s*(?:pro|max|ultra|plus|\+|5g))*",
        r"redmi\s+turbo\s+\d{1,2}[a-z]?(?:\s*(?:pro|max|plus|\+|5g))*",
        r"redmi\s+\d{1,2}[a-z]?(?:\s*(?:pro|max|plus|\+|5g))*",
        r"poco\s+[a-z]\d{1,2}(?:\s*(?:pro|plus|\+|5g))*",
    ],
    "ZTE": [
        r"zte\s+axon\s+\d{1,3}[a-z]?(?:\s*(?:ultra|pro|5g))*",
        r"zte\s+blade\s+[a-z]?\d{1,3}[a-z]?(?:\s*(?:pro|plus|\+|5g))*",
        r"nubia\s+[a-z]?\d{1,3}[a-z]?(?:\s*(?:ultra|pro|plus|\+|5g))*",
        r"redmagic\s+\d{1,2}[a-z]?(?:\s*(?:pro|plus|\+|5g))*",
    ],
    "SAMSUNG": [
        r"galaxy\s+z\s+(?:fold|flip)\s*\d{1,2}(?:\s*(?:fe|ultra|5g))*",
        r"galaxy\s+s\d{2}(?:\s*(?:fe|ultra|plus|\+|edge|5g))*",
        r"galaxy\s+a\d{2,3}(?:\s*(?:fe|pro|plus|\+|5g))*",
        r"galaxy\s+m\d{2,3}(?:\s*(?:pro|plus|\+|5g))*",
        r"galaxy\s+f\d{2,3}(?:\s*(?:pro|plus|\+|5g))*",
        r"galaxy\s+xcover\s*\d{1,2}(?:\s*(?:pro|5g))*",
    ],
}

CUSTOM_SERIES: dict[str, list[str]] = {}

SOURCE_DISPLAY_NAMES = {
    ("MOTOROLA", "MX"): "摩托罗拉墨西哥官网",
    ("OPPO", "MX"): "OPPO墨西哥官网",
    ("VIVO", "MX"): "vivo墨西哥官网",
    ("HONOR", "MX"): "HONOR墨西哥官网",
    ("XIAOMI", "MX"): "小米墨西哥官网",
    ("ZTE", "MX"): "ZTE墨西哥官网",
    ("SAMSUNG", "MX"): "三星墨西哥官网",
    ("MOTOROLA", "CN"): "摩托罗拉中国官网",
    ("OPPO", "CN"): "OPPO中国官网",
    ("VIVO", "CN"): "vivo中国官网",
    ("HONOR", "CN"): "HONOR中国官网",
    ("XIAOMI", "CN"): "小米中国商城",
    ("ZTE", "CN"): "ZTE中国官网",
    ("SAMSUNG", "CN"): "三星中国官网",
    ("SAMSUNG", "KR"): "三星韩国官网",
    ("MOTOROLA", "GLOBAL"): "GSMArena 摩托罗拉",
    ("OPPO", "GLOBAL"): "GSMArena OPPO",
    ("VIVO", "GLOBAL"): "GSMArena vivo",
    ("HONOR", "GLOBAL"): "GSMArena HONOR",
    ("XIAOMI", "GLOBAL"): "GSMArena Xiaomi",
    ("ZTE", "GLOBAL"): "GSMArena ZTE",
    ("SAMSUNG", "GLOBAL"): "GSMArena Samsung",
}


def clean_text(value: Any) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" \t\r\n-|_")


def has_new_label(*values: Any) -> bool:
    text = " ".join(clean_text(value).lower() for value in values if value)
    if not text:
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in NEW_LABEL_PATTERNS)


def set_custom_series_rules(rules: dict[str, list[str]] | None) -> None:
    global CUSTOM_SERIES
    CUSTOM_SERIES = {
        brand.upper(): [clean_text(series) for series in series_list if clean_text(series)]
        for brand, series_list in (rules or {}).items()
    }


def custom_series_patterns(brand: str) -> list[str]:
    brand_upper = brand.upper()
    prefixes = {
        "MOTOROLA": r"(?:motorola|moto)",
        "OPPO": r"oppo",
        "VIVO": r"(?:vivo|iqoo)",
        "HONOR": r"honor",
        "XIAOMI": r"(?:xiaomi|redmi|poco|小米)",
        "ZTE": r"(?:zte|nubia|redmagic)",
        "SAMSUNG": r"(?:samsung\s+)?galaxy",
    }
    suffix = r"(?:\s*(?:pro|max|ultra|lite|plus|\+|mini|fe|edge|flip|fold|5g|4g|e|t|s))*"
    patterns: list[str] = []
    for series in CUSTOM_SERIES.get(brand_upper, []):
        escaped = re.escape(series.lower()).replace(r"\ ", r"\s+")
        prefix = prefixes.get(brand_upper, re.escape(brand.lower()))
        patterns.append(rf"{prefix}\s+{escaped}\s*[a-z0-9]{{0,8}}{suffix}")
    return patterns


def brand_patterns(brand: str) -> list[str]:
    return [*BRAND_PATTERNS.get(brand.upper(), []), *custom_series_patterns(brand)]


def extract_model(brand: str, *values: Any) -> str | None:
    text = clean_text(" ".join(str(value or "") for value in values))
    if not text:
        return None

    for pattern in brand_patterns(brand):
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return format_model(match.group(0), brand)
    return None


def extract_models(brand: str, *values: Any) -> list[str]:
    text = clean_text(" ".join(str(value or "") for value in values))
    if not text:
        return []

    models: list[str] = []
    seen: set[str] = set()
    for pattern in brand_patterns(brand):
        for match in re.finditer(pattern, text, flags=re.IGNORECASE):
            model = format_model(match.group(0), brand)
            key = normalize_model(model, brand)
            if key and key not in seen:
                seen.add(key)
                models.append(model)
    return models


def format_model(model: str, brand: str) -> str:
    model = clean_text(model)
    model = re.sub(r"\s*\+\s*", "+", model)
    model = re.sub(r"\s+", " ", model)
    model = model.strip(" .,-_/|")

    brand_upper = brand.upper()
    if brand_upper == "OPPO":
        model = re.sub(r"^oppo\b", "OPPO", model, flags=re.IGNORECASE)
    elif brand_upper == "VIVO":
        model = re.sub(r"^vivo\b", "vivo", model, flags=re.IGNORECASE)
        model = re.sub(r"^iqoo\b", "iQOO", model, flags=re.IGNORECASE)
    elif brand_upper == "HONOR":
        model = re.sub(r"^honor\b", "HONOR", model, flags=re.IGNORECASE)
    elif brand_upper == "XIAOMI":
        model = re.sub(r"^小米\s*", "Xiaomi ", model, flags=re.IGNORECASE)
        model = re.sub(r"^xiaomi\b", "Xiaomi", model, flags=re.IGNORECASE)
        model = re.sub(r"^redmi\b", "Redmi", model, flags=re.IGNORECASE)
        model = re.sub(r"^poco\b", "POCO", model, flags=re.IGNORECASE)
        model = re.sub(r"\bUltra\s+T\b", "Ultra", model, flags=re.IGNORECASE)
    elif brand_upper == "SAMSUNG":
        model = re.sub(r"^galaxy\b", "Galaxy", model, flags=re.IGNORECASE)
    elif brand_upper == "ZTE":
        model = re.sub(r"^zte\b", "ZTE", model, flags=re.IGNORECASE)
        model = re.sub(r"^nubia\b", "nubia", model, flags=re.IGNORECASE)
        model = re.sub(r"^redmagic\b", "REDMAGIC", model, flags=re.IGNORECASE)
    elif brand_upper == "MOTOROLA":
        model = re.sub(r"^motorola\b", "Motorola", model, flags=re.IGNORECASE)
        model = re.sub(r"^moto\b", "moto", model, flags=re.IGNORECASE)
        model = re.sub(r"^edge\b", "edge", model, flags=re.IGNORECASE)
        model = re.sub(r"^razr\b", "razr", model, flags=re.IGNORECASE)
    return model


def normalize_model(model: str, brand: str) -> str:
    key = clean_text(model).lower()
    brand_tokens = {
        "MOTOROLA": ["motorola", "moto"],
        "OPPO": ["oppo"],
        "VIVO": ["vivo"],
        "HONOR": ["honor"],
        "XIAOMI": ["xiaomi"],
        "ZTE": ["zte"],
        "SAMSUNG": ["samsung"],
    }
    for token in brand_tokens.get(brand.upper(), []):
        key = re.sub(rf"\b{re.escape(token)}\b", " ", key)
    key = key.replace("+", " plus ")
    key = re.sub(r"\b(phone|smartphone|手机|移动电话)\b", " ", key)
    key = re.sub(r"[^a-z0-9]+", "", key)
    return key


def compare_model_key(model: str, brand: str) -> str:
    key = normalize_model(model, brand)
    return re.sub(r"(5g|4g)", "", key)


BRAND_LIBRARY_CODES = {
    "MOTOROLA": "MT",
    "OPPO": "OP",
    "VIVO": "VO",
    "HONOR": "HR",
    "XIAOMI": "XM",
    "ZTE": "ZT",
    "SAMSUNG": "SM",
}


def library_model_compare_keys(model_name: str, brand: str, brand_code: str = "") -> set[str]:
    keys = {compare_model_key(model_name, brand)}
    cleaned = clean_text(model_name)
    code = clean_text(brand_code or BRAND_LIBRARY_CODES.get(brand.upper(), ""))
    if code:
        without_code = re.sub(rf"(?i)^\s*{re.escape(code)}\s+", "", cleaned).strip()
        if without_code and without_code != cleaned:
            keys.add(compare_model_key(without_code, brand))
            if brand.upper() == "SAMSUNG" and re.match(r"(?i)^[samfz]\d", without_code):
                keys.add(compare_model_key(f"Galaxy {without_code}", brand))
            if brand.upper() == "MOTOROLA" and re.match(r"(?i)^(moto|edge|razr)\b", without_code):
                keys.add(compare_model_key(without_code, brand))
    return {key for key in keys if key}


def library_db_config() -> dict[str, Any]:
    return {
        "host": os.getenv("PHONE_LIBRARY_PG_HOST", os.getenv("PHONE_WATCH_PG_HOST", "127.0.0.1")),
        "database": os.getenv("PHONE_LIBRARY_PG_DATABASE", "product_and_model_management"),
        "user": os.getenv("PHONE_LIBRARY_PG_USER", os.getenv("PHONE_WATCH_PG_USER", "postgres")),
        "password": os.getenv("PHONE_LIBRARY_PG_PASSWORD", os.getenv("PHONE_WATCH_PG_PASSWORD", "")),
        "port": int(os.getenv("PHONE_LIBRARY_PG_PORT", os.getenv("PHONE_WATCH_PG_PORT", "5432"))),
        "timeout": int(os.getenv("PHONE_LIBRARY_PG_CONNECT_TIMEOUT", os.getenv("PHONE_WATCH_PG_CONNECT_TIMEOUT", "10"))),
    }


def existing_library_model_keys() -> dict[str, set[str]]:
    if os.getenv("PHONE_WATCH_SKIP_LIBRARY_FILTER", "").lower() in {"1", "true", "yes"}:
        return {}
    if db.db_backend() != "postgres":
        return {}
    if pg8000 is None:
        return {}
    keys: dict[str, set[str]] = {brand: set() for brand in BRAND_LIBRARY_CODES}
    try:
        conn = pg8000.connect(**library_db_config())
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT name, brand_code, brand_name_en
            FROM public.model
            WHERE COALESCE(status, 1) = 1
              AND name IS NOT NULL
            """
        )
        for name, brand_code, brand_name_en in cursor.fetchall():
            code = clean_text(brand_code)
            brand = next((item_brand for item_brand, item_code in BRAND_LIBRARY_CODES.items() if item_code == code), "")
            if not brand and brand_name_en:
                brand_name = clean_text(brand_name_en).upper()
                brand = next((item_brand for item_brand in BRAND_LIBRARY_CODES if item_brand in brand_name), "")
            if not brand:
                continue
            keys.setdefault(brand, set()).update(library_model_compare_keys(str(name), brand, code))
        conn.close()
    except Exception as exc:
        print(f"[WARN] existing model library filter skipped: {exc}")
    return keys


def display_source_name(brand: str, country: str, fallback: str = "") -> str:
    cleaned_fallback = clean_text(fallback)
    if "walmart" in cleaned_fallback.lower():
        return cleaned_fallback
    return SOURCE_DISPLAY_NAMES.get((brand.upper(), country.upper()), clean_text(fallback))


def looks_like_phone(model: str) -> bool:
    lowered = model.lower()
    if not re.search(r"\d", lowered):
        return False
    for word in ACCESSORY_WORDS:
        if word.isascii():
            if re.search(rf"\b{re.escape(word)}\b", lowered):
                return False
        elif word in lowered:
                return False
    return True


def _first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text, flags=re.IGNORECASE)
    if not match:
        return None
    for group in match.groups():
        if group is None:
            continue
        try:
            return int(group)
        except ValueError:
            continue
    return None


def _date_year(value: str | None) -> int | None:
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def is_current_generation(
    brand: str,
    model: str,
    *,
    release_date: str | None = None,
    launch_date: str | None = None,
    as_of_year: int | None = None,
) -> bool:
    """Reject stale models when official pages keep old products under New labels."""
    year = as_of_year or datetime.now().year
    known_year = max((_date_year(release_date) or 0), (_date_year(launch_date) or 0))
    if known_year:
        return known_year >= year

    display = clean_text(model).lower()
    lowered = re.sub(r"[^a-z0-9]+", "", display)
    brand = brand.upper()

    if brand == "SAMSUNG":
        if "galaxyzfold" in lowered or "galaxyzflip" in lowered:
            number = _first_int(r"galaxy\s+z\s+(?:fold|flip)\s*(\d+)", display)
            return bool(number and number >= 7)
        if "galaxys" in lowered:
            number = _first_int(r"galaxy\s+s(\d+)", display)
            return bool(number and number >= 25)
        if "galaxya" in lowered:
            number = _first_int(r"galaxy\s+a(\d+)", display)
            return bool(number and number >= 36)
        return True

    if brand == "HONOR":
        if "honormagicv" in lowered or re.search(r"honor\s+magic\s*v", display):
            number = _first_int(r"honor\s+magic\s*v\s*(\d+)|honor\s+magicv\s*(\d+)", display)
            return bool(number and number >= 5)
        if "honormagic" in lowered or re.search(r"honor\s+magic\s*\d", display):
            number = _first_int(r"honor\s+magic\s*(\d+)|honor\s+magic(\d+)", display)
            return bool(number and number >= 8)
        if re.search(r"honor\s+x\d+", display):
            number = _first_int(r"honor\s+x(\d+)", display)
            return bool(number and number >= 9)
        number = _first_int(r"honor\s+(\d+)", display)
        return bool(number and number >= 400)

    if brand == "MOTOROLA":
        if "edge" in lowered:
            number = _first_int(r"edge\s+(\d+)", display)
            return bool(number and number >= 60)
        if "razr" in lowered:
            number = _first_int(r"razr\s+(\d+)", display)
            return bool(number and number >= 60)
        if "motog" in lowered:
            number = _first_int(r"moto\s+g(\d+)", display)
            return bool(number and number >= 56)
        return True

    if brand == "OPPO":
        if "findx" in lowered:
            number = _first_int(r"find\s+x(\d+)", display)
            return bool(number and number >= 8)
        if "findn" in lowered:
            number = _first_int(r"find\s+n(\d+)", display)
            return bool(number and number >= 5)
        if "reno" in lowered:
            number = _first_int(r"reno\s*(\d+)", display)
            return bool(number and number >= 15)
        if re.search(r"oppo\s+a\d+", display):
            number = _first_int(r"oppo\s+a(\d+)", display)
            return bool(number and number == 6)
        if re.search(r"oppo\s+k\d+", display):
            number = _first_int(r"oppo\s+k(\d+)", display)
            return bool(number and number >= 13)
        return True

    if brand == "XIAOMI":
        if "redminote" in lowered:
            number = _first_int(r"redmi\s+note\s+(\d+)", display)
            return bool(number and number >= 15)
        if "redmik" in lowered:
            number = _first_int(r"redmi\s+k(\d+)", display)
            return bool(number and number >= 90)
        if "redmiturbo" in lowered:
            number = _first_int(r"redmi\s+turbo\s+(\d+)", display)
            return bool(number and number >= 5)
        if "redmi" in lowered:
            number = _first_int(r"redmi\s+(\d+)", display)
            return bool(number and number >= 15)
        if "xiaomi" in lowered:
            number = _first_int(r"xiaomi\s+(\d+)", display)
            return bool(number and number >= 15)
        if "poco" in lowered:
            family = re.search(r"poco\s+([a-z])(\d+)", display, flags=re.IGNORECASE)
            if not family:
                return True
            letter, number = family.group(1).lower(), int(family.group(2))
            return (letter == "f" and number >= 7) or (letter in {"x", "m"} and number >= 7)
        return True

    if brand == "VIVO":
        if "vivox" in lowered:
            number = _first_int(r"vivo\s+x\s*(\d+)", display)
            return bool(number and number >= 200)
        if "vivov" in lowered:
            number = _first_int(r"vivo\s+v(\d+)", display)
            return bool(number and number >= 50)
        if "vivoy" in lowered:
            number = _first_int(r"vivo\s+y(\d+)", display)
            return bool(number and number >= 300)
        if "vivos" in lowered:
            number = _first_int(r"vivo\s+s(\d+)", display)
            return bool(number and number >= 60)
        if "iqoo" in lowered:
            number = _first_int(r"iqoo\s+(\d+)", display)
            return bool(number and number >= 13)
        return True

    if brand == "ZTE":
        number = _first_int(r"(?:axon|blade|nubia|redmagic)\s+[a-z]?(\d+)", display)
        return True if number is None else number >= 10

    return True


def has_non_phone_context(*values: Any) -> bool:
    text = clean_text(" ".join(str(value or "") for value in values)).lower()
    if not text:
        return False
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in NON_PHONE_CONTEXT_PATTERNS)


def has_model_text_evidence(brand: str, model: str, *values: Any) -> bool:
    text = clean_text(" ".join(str(value or "") for value in values))
    if not text:
        return False
    target_key = compare_model_key(model, brand)
    if not target_key:
        return False
    for found in extract_models(brand, text):
        if compare_model_key(found, brand) == target_key:
            return True
    return False


def is_placeholder_image(value: Any) -> bool:
    url = clean_text(value).lower()
    if not url:
        return True
    bad_parts = (
        "placeholder",
        "lazyload",
        "spacer",
        "blank.",
        "logo",
        "favicon",
        "sprite",
        "icon-",
        "/icons/",
    )
    return any(part in url for part in bad_parts)


def parse_date_to_iso(value: Any) -> str | None:
    text = clean_text(value)
    if not text:
        return None

    candidates = [
        r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})",
        r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})",
    ]
    for pattern in candidates:
        match = re.search(pattern, text)
        if not match:
            continue
        parts = [int(part) for part in match.groups()]
        try:
            if len(str(parts[0])) == 4:
                date = datetime(parts[0], parts[1], parts[2])
            else:
                date = datetime(parts[2], parts[1], parts[0])
            time_match = re.search(r"([01]?\d|2[0-3])[:：]([0-5]\d)", text[match.end() : match.end() + 24])
            if time_match:
                return f"{date.date().isoformat()} {int(time_match.group(1)):02d}:{time_match.group(2)}"
            return date.date().isoformat()
        except ValueError:
            continue

    cn_month_day = re.search(r"(\d{1,2})\s*月\s*(\d{1,2})\s*日?", text)
    if cn_month_day:
        year_match = re.search(r"(20\d{2})", text[: cn_month_day.start()])
        year = int(year_match.group(1)) if year_match else datetime.now().year
        month, day = (int(part) for part in cn_month_day.groups())
        try:
            date = datetime(year, month, day)
        except ValueError:
            return None
        time_match = re.search(r"([01]?\d|2[0-3])[:：]([0-5]\d)", text[cn_month_day.end() : cn_month_day.end() + 24])
        if time_match:
            return f"{date.date().isoformat()} {int(time_match.group(1)):02d}:{time_match.group(2)}"
        return date.date().isoformat()

    month_match = re.search(r"(\d{4})[-/.年](\d{1,2})", text)
    if month_match:
        year, month = (int(part) for part in month_match.groups())
        try:
            return datetime(year, month, 1).date().isoformat()
        except ValueError:
            return None
    return None


def payload_text(payload: dict[str, Any]) -> str:
    pieces: list[str] = []
    for key in ("name", "title", "description", "badge", "sku", "model", "price", "lowPrice"):
        value = payload.get(key)
        if isinstance(value, (str, int, float)):
            pieces.append(str(value))
    return " ".join(pieces)


def extract_price(*values: Any) -> str | None:
    text = clean_text(" ".join(str(value or "") for value in values))
    if not text:
        return None
    patterns = [
        r"(?:desde|from|起|起售价|售价|价格|precio)[^\d$¥￥]{0,12}([$¥￥]?\s?\d[\d,.\s]{2,})",
        r"([$¥￥]\s?\d[\d,.\s]{2,})",
        r"(\d[\d,.\s]{2,}\s?(?:MXN|CNY|RMB|KRW|₩|元|￥|¥))",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        price = clean_text(match.group(1))
        price = re.sub(r"\s+", "", price)
        digits = re.sub(r"\D", "", price)
        if digits and int(digits) >= 100:
            return price
    return None


def is_unreleased_context(*values: Any) -> bool:
    text = clean_text(" ".join(str(value or "") for value in values))
    return any(
        token in text
        for token in ("预约", "预售", "立即预约", "敬请期待", "即将发布", "即将开售", "新品发布", "coming soon")
    )


def _date_value(value: Any):
    text = clean_text(value)
    if len(text) < 10:
        return None
    try:
        return datetime.fromisoformat(text[:10]).date()
    except ValueError:
        return None


def has_recent_or_future_date(*values: Any, days: int = 45) -> bool:
    cutoff = datetime.now().date() - timedelta(days=days)
    return any((parsed := _date_value(value)) and parsed >= cutoff for value in values)


def has_future_date(*values: Any) -> bool:
    today = datetime.now().date()
    return any((parsed := _date_value(value)) and parsed > today for value in values)


def clean_raw_item(
    row: sqlite3.Row,
    *,
    clean_stage: str,
    new_only: bool = False,
    origin_current_fallback: bool = False,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(row["raw_payload"] or "{}")
    except json.JSONDecodeError:
        payload = {}

    brand = str(row["brand"]).upper()
    title = clean_text(row["raw_title"])
    badge = clean_text(row["raw_badge"])
    context_values = [
        payload.get(key)
        for key in ("name", "title", "link_text", "category", "categoryName", "sku")
        if isinstance(payload.get(key), (str, int, float))
    ]
    context = " ".join(clean_text(value) for value in context_values)
    if "undefined" in clean_text(row["page_url"]).lower():
        return None
    if has_non_phone_context(title, badge, context, row["page_url"]):
        return None
    evidence_text = payload_text(payload)
    model = extract_model(brand, title, badge, evidence_text)
    if not model:
        url_model = extract_model(brand, row["page_url"])
        if url_model and has_model_text_evidence(brand, url_model, title, badge, evidence_text):
            model = url_model
    if not model or not looks_like_phone(model):
        return None
    is_new = has_new_label(badge)
    is_walmart_mx_listing = str(payload.get("source") or "").lower() == "walmart_mx_search"
    unreleased_context = is_unreleased_context(badge, payload_text(payload), row["raw_title"], row["raw_release_date"], row["raw_launch_date"])

    normalized = normalize_model(model, brand)
    if not normalized:
        return None

    release_date = parse_date_to_iso(row["raw_release_date"]) or parse_date_to_iso(
        payload.get("releaseDate") or payload.get("datePublished") or payload.get("dateCreated")
    )
    launch_date = parse_date_to_iso(row["raw_launch_date"]) or parse_date_to_iso(
        payload.get("launchDate") or payload.get("startDate") or payload.get("availabilityStarts")
    )
    date_says_new = has_recent_or_future_date(release_date, launch_date)
    date_says_unreleased = has_future_date(release_date, launch_date)
    country = str(row["country"]).upper()
    current_generation = is_current_generation(brand, model, release_date=release_date, launch_date=launch_date)
    official_trusted_new = (is_new or date_says_new) and (country == "MX" or (country == "CN" and brand in {"VIVO", "OPPO"}))
    if not is_walmart_mx_listing and not current_generation and not official_trusted_new:
        return None
    fallback_new = (
        (origin_current_fallback and country in {"CN", "KR", "GLOBAL"} and current_generation)
        or (brand in {"XIAOMI", "ZTE"} and country == "MX" and current_generation)
    )
    if new_only and not is_walmart_mx_listing and not (is_new or date_says_new or fallback_new):
        return None

    price = extract_price(
        row["raw_price"] if "raw_price" in row.keys() else "",
        payload.get("price"),
        payload.get("lowPrice"),
        payload.get("offers"),
        payload_text(payload),
    )

    return {
        "brand": brand,
        "country": country,
        "model": model,
        "normalized_model": normalized,
        "image_url": None if is_placeholder_image(row["raw_image_url"]) else clean_text(row["raw_image_url"]),
        "price": price,
        "release_date": release_date,
        "launch_date": launch_date,
        "source_url": clean_text(row["page_url"]) or clean_text(row["source_url"]),
        "source_name": display_source_name(brand, country, row["source_name"]),
        "badge": (
            "Walmart MX \u5728\u552e"
            if is_walmart_mx_listing
            else (
                "\u65b0\u54c1\u9884\u544a"
                if unreleased_context or date_says_unreleased
                else ("\u65b0\u54c1" if is_new or date_says_new else ("\u5b98\u7f51\u5f53\u524d\u673a\u578b" if fallback_new else (badge or None)))
            )
        ),
        "first_seen_at": row["fetched_at"],
        "last_seen_at": row["fetched_at"],
        "clean_stage": clean_stage,
    }


def clean_scope(
    conn: sqlite3.Connection,
    scope: str,
    *,
    new_only: bool = False,
    today_only: bool = False,
    latest_only: bool = False,
    run_id: int | None = None,
    today: str | None = None,
    origin_current_fallback: bool = False,
) -> int:
    set_custom_series_rules(db.custom_series_map(conn))
    normalized_scope = scope.lower()
    if normalized_scope == "mx":
        countries = ["MX"]
        stage = "mx_cleaned"
    elif normalized_scope in {"origin", "cn_kr"}:
        countries = ["CN", "KR", "GLOBAL"]
        stage = "origin_cleaned"
    elif normalized_scope == "all":
        countries = ["MX", "CN", "KR", "GLOBAL"]
        stage = "cleaned"
    else:
        raise ValueError("scope must be mx, origin, cn_kr, or all")

    count = 0
    seen: set[tuple[str, str, str]] = set()
    if run_id is not None:
        raw_rows = db.raw_items_for_run_scope(conn, run_id, countries)
    elif latest_only:
        latest_date = db.latest_raw_date(conn, countries)
        raw_rows = db.raw_items_today_for_scope(conn, countries, latest_date) if latest_date else []
    elif today_only:
        raw_rows = db.raw_items_today_for_scope(conn, countries, today or datetime.now().date().isoformat())
    else:
        raw_rows = db.raw_items_for_scope(conn, countries)
    for raw in raw_rows:
        cleaned = clean_raw_item(
            raw,
            clean_stage=stage,
            new_only=new_only,
            origin_current_fallback=origin_current_fallback,
        )
        if not cleaned:
            continue
        key = (cleaned["brand"], cleaned["country"], cleaned["normalized_model"])
        if key in seen:
            continue
        seen.add(key)
        db.upsert_phone(conn, cleaned)
        count += 1
    return count


def compare_and_clean_candidates(conn: sqlite3.Connection) -> int:
    mark_non_phone_records(conn)
    db.delete_resolved_candidates(conn)
    library_keys = existing_library_model_keys()
    delete_library_existing_candidates(conn, library_keys)
    count = 0
    mx_cache: dict[str, set[str]] = {}
    for phone in db.origin_phones_for_compare(conn):
        brand = str(phone["brand"]).upper()
        if compare_model_key(phone["model"], brand) in library_keys.get(brand, set()):
            continue
        if brand not in mx_cache:
            mx_cache[brand] = mx_available_compare_keys(conn, brand)
        if compare_model_key(phone["model"], brand) in mx_cache[brand]:
            continue
        if not looks_like_phone(phone["model"]):
            continue
        reason = f"{phone['country']} 已收录，MX 未收录"
        db.upsert_candidate(
            conn,
            {
                "brand": brand,
                "source_country": phone["country"],
                "missing_country": "MX",
                "model": phone["model"],
                "normalized_model": phone["normalized_model"],
                "image_url": phone["image_url"],
                "price": phone["price"] if "price" in phone.keys() else None,
                "release_date": phone["release_date"],
                "launch_date": phone["launch_date"],
                "source_url": phone["source_url"],
                "source_name": phone["source_name"] if "source_name" in phone.keys() else None,
                "reason": reason,
                "first_seen_at": phone["first_seen_at"],
                "last_seen_at": phone["last_seen_at"],
            },
        )
        count += 1
    return count


def delete_library_existing_candidates(conn: sqlite3.Connection, library_keys: dict[str, set[str]]) -> int:
    if not library_keys:
        return 0
    deleted = 0
    rows = conn.execute("SELECT id, brand, model FROM candidates").fetchall()
    for row in rows:
        brand = str(row["brand"]).upper()
        if compare_model_key(row["model"], brand) not in library_keys.get(brand, set()):
            continue
        cursor = conn.execute("DELETE FROM candidates WHERE id = ?", (row["id"],))
        deleted += int(cursor.rowcount or 0)
    return deleted


def mx_available_compare_keys(conn: sqlite3.Connection, brand: str) -> set[str]:
    keys = {
        compare_model_key(row["model"], brand)
        for row in db.list_phones(conn, country="MX", brand=brand)
        if looks_like_phone(row["model"])
    }
    keys |= mx_raw_available_models(conn, brand)
    return keys


def mx_raw_available_models(conn: sqlite3.Connection, brand: str) -> set[str]:
    models: set[str] = set()
    for raw in db.raw_items_for_scope(conn, ["MX"]):
        if str(raw["brand"]).upper() != brand.upper():
            continue
        cleaned = clean_raw_item(raw, clean_stage="mx_available", new_only=False)
        if cleaned and cleaned["country"] == "MX":
            models.add(compare_model_key(cleaned["model"], brand))
    return models


def mark_non_phone_records(conn: sqlite3.Connection) -> int:
    updated = 0
    for table in ("phones", "candidates"):
        rows = conn.execute(
            f"""
            SELECT id, model, source_url
            FROM {table}
            WHERE sampling_status != '忽略'
            """
        ).fetchall()
        for row in rows:
            if not looks_like_phone(row["model"]) or has_non_phone_context(row["model"], row["source_url"]):
                db.set_sampling_status(conn, table, int(row["id"]), "忽略")
                updated += 1
    return updated
