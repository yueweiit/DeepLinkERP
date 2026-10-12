from __future__ import annotations

from datetime import date
from typing import Any


def row_to_dict(row: Any, molding_tipos: list[dict] | None = None) -> dict[str, Any]:
    data = {key: row[key] for key in row.keys()}
    if data.get("badge_override"):
        data["badge"] = data["badge_override"]
    data["sale_status"] = sale_status(data)
    if molding_tipos is not None:
        data["molding_tipos"] = molding_tipos
    return data


def _parse_iso(value: Any) -> date | None:
    text = str(value or "").strip()
    if len(text) < 10:
        return None
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def sale_status(row: dict[str, Any]) -> str:
    if row.get("sale_status_override"):
        return str(row["sale_status_override"])

    today = date.today()
    release_date = _parse_iso(row.get("release_date"))
    launch_date = _parse_iso(row.get("launch_date"))
    badge = str(row.get("badge") or "")
    payload_text = " ".join(str(row.get(key) or "") for key in ("reason", "source_name"))
    source_url = str(row.get("source_url") or "")
    status_text = f"{badge} {payload_text} {source_url}"
    if any(token in status_text for token in ("\u65b0\u54c1\u9884\u544a", "\u9884\u7ea6", "\u9884\u552e", "\u656c\u8bf7\u671f\u5f85", "\u5373\u5c06\u53d1\u5e03", "\u5373\u5c06\u5f00\u552e")):
        return "\u672a\u53d1\u552e"
    if release_date and release_date > today:
        return "\u672a\u53d1\u5e03"
    if launch_date and launch_date > today:
        return "\u672a\u4e0a\u5e02"
    return "\u5df2\u552e"
