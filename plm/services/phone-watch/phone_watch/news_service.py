from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from . import db
from .config import DEFAULT_NEWS_CONFIG, load_news_config
from .news_crawler import collect_news_sources_to_db


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def collect_news_once(
    db_path: str | Path,
    *,
    news_config: str | Path = DEFAULT_NEWS_CONFIG,
    brand: str | None = None,
    source_type: str | None = None,
    timeout: int = 20,
    render_mode: str = "config",
    allow_render_fallback: bool = True,
    now: str | None = None,
) -> dict[str, Any]:
    db.init_db(db_path)
    config = load_news_config(news_config)
    with db.connect(db_path) as conn:
        current_time = now or utc_now()
        previous_finished_at = db.latest_finished_run_time(conn, mode="collect-news")
        if previous_finished_at:
            window_start = previous_finished_at
        else:
            current_dt = datetime.fromisoformat(current_time.replace("Z", "+00:00"))
            window_start = (current_dt - timedelta(hours=24)).isoformat(timespec="seconds")
        window_end = current_time
        run_id = db.start_run(conn, "collect-news", current_time, notes="news collect")
        counts = collect_news_sources_to_db(
            conn,
            config,
            brand=brand,
            source_type=source_type,
            timeout=timeout,
            render_mode=render_mode,
            allow_render_fallback=allow_render_fallback,
            now=current_time,
            window_start=window_start,
            window_end=window_end,
            collect_run_id=run_id,
        )
        db.finish_run(conn, run_id, window_end)
        deleted = db.cleanup_old_news_items(conn, retention_days=config.retention_days, now=now)

    return {
        "ok": True,
        "window_start": window_start,
        "window_end": window_end,
        "counts": counts,
        "cleanup_deleted": deleted,
        "retention_days": config.retention_days,
    }
