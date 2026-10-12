from __future__ import annotations

from pathlib import Path

from . import db
from .presentation import row_to_dict
from .ui import render_app_html


def is_news_failure_marker(row) -> bool:
    title = str(row["title"] if "title" in row.keys() else "")
    error = row["last_error"] if "last_error" in row.keys() else None
    return bool(error) and title.endswith(("当日爬取失败", "褰撴棩鐖彇澶辫触"))


def news_export_payload(conn) -> dict[str, object]:
    rows = [row for row in db.list_recent_news_items(conn) if not is_news_failure_marker(row)]
    return {
        "status": "ok",
        "mode": "recent_retained",
        "date": "today",
        "window_start": None,
        "window_end": None,
        "fallback_used": False,
        "fallback_limit": 3,
        "retention_days": 7,
        "crawl_failed": False,
        "crawl_error": None,
        "empty_today": False,
        "empty_message": "",
        "fallback_note": False,
        "fallback_message": "",
        "items": [row_to_dict(row) for row in rows],
    }


def export_html(db_path: str | Path, output_path: str | Path) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with db.connect(db_path) as conn:
        payload = {
            "summary": db.summary(conn),
            "phones": [row_to_dict(row) for row in db.list_phones(conn)],
            "candidates": [row_to_dict(row) for row in db.list_candidates(conn)],
            "news": news_export_payload(conn),
        }
    output.write_text(render_app_html(api_mode=False, data=payload), encoding="utf-8")
    return output.resolve()
