from __future__ import annotations

import argparse
import os
import traceback
from datetime import datetime, timezone
from pathlib import Path

from . import db
from .cleaning import clean_scope, compare_and_clean_candidates, mark_non_phone_records
from .config import DEFAULT_CONFIG, DEFAULT_NEWS_CONFIG, load_sources, select_sources
from .crawler import crawl_sources_to_db, enrich_missing_images, enrich_missing_prices
from .dingtalk_sync import load_config as load_dingtalk_config
from .dingtalk_sync import sync_rows_to_dingtalk
from .dingtalk_http import run_server as run_dingtalk_server
from .launcher import start_background
from .news_service import collect_news_once
from .static_export import export_html
from .webapp import run_server
from .scheduler import run_daily


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log_step(message: str) -> None:
    print(f"[STEP] {datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def add_common_filters(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--brand", help="只处理某个品牌，例如 SAMSUNG")
    parser.add_argument("--country", help="只处理某个国家/地区，例如 MX、CN、KR")


def add_storage_options(parser: argparse.ArgumentParser, *, include_config: bool = True) -> None:
    parser.add_argument("--db", default=argparse.SUPPRESS, help="仅 SQLite 后端使用的数据库路径，默认 data/phones.sqlite")
    if include_config:
        parser.add_argument("--config", default=argparse.SUPPRESS, help="来源配置 JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="手机新品采集、清洗、SQLite/PostgreSQL 入库和网页展示")
    parser.add_argument("--db", default=str(db.DEFAULT_DB), help="仅 SQLite 后端使用的数据库路径，默认 data/phones.sqlite")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="来源配置 JSON")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_db = subparsers.add_parser("init-db", help="初始化当前数据库后端表结构")
    add_storage_options(init_db, include_config=False)

    check_db = subparsers.add_parser("check-db", help="检查当前数据库连接")
    add_storage_options(check_db, include_config=False)

    crawl = subparsers.add_parser("crawl", help="爬取来源并写入 raw_items")
    add_storage_options(crawl)
    add_common_filters(crawl)
    crawl.add_argument("--include-reference", action="store_true", help="包含 GSMArena 等参考来源")
    crawl.add_argument("--max-pages", type=int, default=6, help="每个来源最多追踪的商品页数量")
    crawl.add_argument("--delay", type=float, default=1.0, help="每次请求间隔秒数")
    crawl.add_argument("--timeout", type=int, default=25, help="单次请求超时秒数")

    clean = subparsers.add_parser("clean", help="清洗 raw_items 并写入 phones")
    add_storage_options(clean, include_config=False)
    clean.add_argument("--scope", choices=["mx", "origin", "all"], default="all")
    clean.add_argument("--new-only", action="store_true", help="只保留带新品标签的记录")
    clean.add_argument("--today-only", action="store_true", help="只清洗今天采集的记录")
    clean.add_argument("--latest-only", action="store_true", help="只清洗数据库里最新采集日期的记录")

    compare = subparsers.add_parser("compare", help="生成中国/韩国已上新但墨西哥未上新的候选机型")
    add_storage_options(compare, include_config=False)

    pipeline = subparsers.add_parser("pipeline", help="爬取、三次清洗、候选生成一条龙")
    add_storage_options(pipeline)
    add_common_filters(pipeline)
    pipeline.add_argument("--include-reference", action="store_true", help="包含 GSMArena 等参考来源")
    pipeline.add_argument("--max-pages", type=int, default=6, help="每个来源最多追踪的商品页数量")
    pipeline.add_argument("--delay", type=float, default=1.0, help="每次请求间隔秒数")
    pipeline.add_argument("--timeout", type=int, default=25, help="单次请求超时秒数")
    pipeline.add_argument("--new-only", action="store_true", help="只保留带新品标签的记录")
    pipeline.add_argument("--today-only", action="store_true", help="只处理今天采集的记录")

    collect = subparsers.add_parser("collect", help="生产采集任务：爬取全部来源并按本次 run_id 重建展示数据")
    add_storage_options(collect)
    collect.add_argument("--max-pages", type=int, default=6, help="每个来源最多追踪的商品页数量")
    collect.add_argument("--delay", type=float, default=0.5, help="每次请求间隔秒数")
    collect.add_argument("--timeout", type=int, default=20, help="单次请求超时秒数")
    collect.add_argument("--new-only", action="store_true", default=True, help="只保留带新品标签的记录")
    collect.add_argument("--all-models", action="store_true", help="不过滤新品标签，展示本次采集到的全部手机型号")
    collect.add_argument("--retention-months", type=int, default=5, help="未开模/部分开模线索保留月数，默认 5 个月")
    collect.add_argument("--export-out", default="data/phone_watch.html", help="静态 HTML 备份输出路径")

    collect_news = subparsers.add_parser("collect-news", help="手动采集新闻来源并写入 news_items")
    add_storage_options(collect_news, include_config=False)
    collect_news.add_argument("--news-config", default=str(DEFAULT_NEWS_CONFIG), help="新闻来源配置 JSON")
    collect_news.add_argument("--brand", help="只采集某个品牌，例如 VIVO")
    collect_news.add_argument(
        "--source-type",
        choices=["ithome_brand_search", "ithome_phone_today"],
        help="只采集某类新闻来源",
    )
    collect_news.add_argument("--timeout", type=int, default=20, help="单次请求超时秒数")
    collect_news.add_argument(
        "--render-mode",
        choices=["config", "always", "never", "playwright"],
        default="config",
        help="新闻来源渲染模式：config 按配置，always 全部使用 Playwright，never 禁用 Playwright",
    )
    collect_news.add_argument(
        "--no-render-fallback",
        action="store_true",
        help="Playwright 渲染失败时不回退静态 HTML，直接计入错误",
    )
    collect_news.add_argument("--now", help="指定当前时间，仅用于测试清理逻辑，格式为 ISO 时间")

    serve = subparsers.add_parser("serve", help="启动本地网页")
    add_storage_options(serve, include_config=False)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)

    schedule = subparsers.add_parser("schedule", help="按 Asia/Shanghai 时区每天定时采集")
    add_storage_options(schedule, include_config=False)
    schedule.add_argument("--hour", type=int, default=8)
    schedule.add_argument("--minute", type=int, default=0)

    export = subparsers.add_parser("export-html", help="导出一个可直接打开的本地 HTML 查看页")
    add_storage_options(export, include_config=False)
    export.add_argument("--out", default="data/phone_watch.html", help="输出 HTML 路径")

    reset_status = subparsers.add_parser("reset-pending", help="把自动生成的待打样批量改回未处理")
    add_storage_options(reset_status, include_config=False)

    cleanup = subparsers.add_parser("cleanup-stale", help="清理超过保留期且未开模的数据，已开模永久保留")
    add_storage_options(cleanup, include_config=False)
    cleanup.add_argument("--months", type=int, default=5, help="保留月数，默认 5 个月")

    sync_business = subparsers.add_parser("sync-business-tables", help="同步来源收录表和开模记录表")
    add_storage_options(sync_business, include_config=False)

    sync_dingtalk = subparsers.add_parser("sync-dingtalk", help="同步数据库机型到钉钉审批表单")
    add_storage_options(sync_dingtalk, include_config=False)
    sync_dingtalk.add_argument("--source-table", choices=["phones", "candidates"], default="candidates")
    sync_dingtalk.add_argument("--status", help="只同步某个 sampling_status，例如 未开模/部分开模")
    sync_dingtalk.add_argument("--seen-date", help="只同步 first_seen_at 为该日期的数据，格式 YYYY-MM-DD")
    sync_dingtalk.add_argument("--latest-date", action="store_true", help="只同步数据库最新采集日期的数据")
    sync_dingtalk.add_argument("--limit", type=int, default=50)
    sync_dingtalk.add_argument("--timeout", type=int, default=20)
    sync_dingtalk.add_argument("--dry-run", action="store_true", help="只写同步预览日志，不调用钉钉")
    sync_dingtalk.add_argument("--model-field", default="Modelos型号")
    sync_dingtalk.add_argument("--price-field", default="价格Precio de Celular")
    sync_dingtalk.add_argument("--page-field", default="网站链接Pagina")
    sync_dingtalk.add_argument("--sales-channel-field", default="销售渠道 Canales venta")

    serve_dingtalk = subparsers.add_parser("serve-dingtalk", help="启动钉钉连接器 HTTP 服务")
    serve_dingtalk.add_argument("--host", default="127.0.0.1")
    serve_dingtalk.add_argument("--port", type=int, default=5011)

    rebuild = subparsers.add_parser("rebuild-derived", help="清空 phones/candidates 后重新清洗生成")
    add_storage_options(rebuild, include_config=False)
    rebuild.add_argument("--new-only", action="store_true", help="只保留带新品标签的记录")
    rebuild.add_argument("--today-only", action="store_true", help="只处理今天采集的记录")
    rebuild.add_argument("--latest-only", action="store_true", help="只处理数据库里最新采集日期的记录")

    enrich = subparsers.add_parser("enrich-images", help="打开缺图机型的发布链接并回填图片")
    add_storage_options(enrich, include_config=False)
    enrich.add_argument("--timeout", type=int, default=20)
    enrich.add_argument("--limit", type=int, default=30)

    enrich_prices = subparsers.add_parser("enrich-prices", help="打开发布链接并回填起步价")
    add_storage_options(enrich_prices, include_config=False)
    enrich_prices.add_argument("--timeout", type=int, default=20)
    enrich_prices.add_argument("--limit", type=int, default=80)

    start_bg = subparsers.add_parser("start-server", help="后台启动本地网页服务")
    add_storage_options(start_bg, include_config=False)
    start_bg.add_argument("--host", default="127.0.0.1")
    start_bg.add_argument("--port", type=int, default=8000)
    start_bg.add_argument("--log", default="server.log")
    start_bg.add_argument("--pid", default="server.pid")
    return parser


def command_init_db(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    if db.db_backend(args.db) == "postgres":
        print("PostgreSQL 表结构已初始化")
    else:
        print(f"SQLite 已初始化: {Path(args.db).resolve()}")


def command_check_db(args: argparse.Namespace) -> None:
    result = db.check_connection(args.db)
    print(f"数据库连接正常: backend={result['backend']} ok={result['ok']}")


def command_crawl(args: argparse.Namespace) -> None:
    sources = select_sources(
        load_sources(args.config),
        brand=args.brand,
        country=args.country,
        include_reference=args.include_reference,
    )
    if not sources:
        raise SystemExit("没有匹配的采集来源")
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        run_id = db.start_run(conn, "crawl", utc_now())
        counts = crawl_sources_to_db(
            conn,
            sources,
            max_pages=args.max_pages,
            delay_seconds=args.delay,
            timeout=args.timeout,
            run_id=run_id,
        )
        db.finish_run(conn, run_id, utc_now())
    for key, count in counts.items():
        print(f"{key}: raw_items +{count}")


def command_clean(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        count = clean_scope(conn, args.scope, new_only=args.new_only, today_only=args.today_only, latest_only=args.latest_only)
        ignored = mark_non_phone_records(conn)
        images = db.fill_missing_images(conn)
    print(f"清洗完成: phones upsert {count}, 非手机标记忽略 {ignored}, 图片回填 {images}")


def command_compare(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        count = compare_and_clean_candidates(conn)
        images = db.fill_missing_images(conn)
    print(f"候选机型更新完成: candidates upsert {count}, 图片回填 {images}")


def command_pipeline(args: argparse.Namespace) -> None:
    sources = select_sources(
        load_sources(args.config),
        brand=args.brand,
        country=args.country,
        include_reference=args.include_reference,
    )
    if not sources:
        raise SystemExit("没有匹配的采集来源")

    db.init_db(args.db)
    with db.connect(args.db) as conn:
        run_id = db.start_run(conn, "pipeline", utc_now())
        counts = crawl_sources_to_db(
            conn,
            sources,
            max_pages=args.max_pages,
            delay_seconds=args.delay,
            timeout=args.timeout,
            run_id=run_id,
        )
        mx_count = clean_scope(conn, "mx", new_only=args.new_only, today_only=args.today_only, latest_only=args.latest_only)
        origin_count = clean_scope(
            conn,
            "origin",
            new_only=args.new_only,
            today_only=args.today_only,
            latest_only=args.latest_only,
            origin_current_fallback=True,
        )
        ignored_count = mark_non_phone_records(conn)
        candidate_count = compare_and_clean_candidates(conn)
        image_count = db.fill_missing_images(conn)
        db.finish_run(conn, run_id, utc_now())

    for key, count in counts.items():
        print(f"{key}: raw_items +{count}")
    print(f"第一次清洗 墨西哥: phones upsert {mx_count}")
    print(f"第二次清洗 中国/韩国: phones upsert {origin_count}")
    print(f"非手机标记忽略: {ignored_count}")
    print(f"图片回填: {image_count}")
    print(f"第三次清洗 候选结果: candidates upsert {candidate_count}")


def command_collect(args: argparse.Namespace) -> None:
    log_step("collect command start")
    sources = select_sources(load_sources(args.config), include_reference=True)
    if not sources:
        raise SystemExit("没有可用采集来源")

    db.init_db(args.db)
    new_only = False if args.all_models else args.new_only
    try:
        with db.connect(args.db) as conn:
            run_id = db.start_run(conn, "collect", utc_now(), notes="production collect")
            log_step(f"run_id={run_id} sources={len(sources)}")
            status_snapshot = db.snapshot_sampling_statuses(conn)
            log_step("crawl sources start")
            counts = crawl_sources_to_db(
                conn,
                sources,
                max_pages=args.max_pages,
                delay_seconds=args.delay,
                timeout=args.timeout,
                run_id=run_id,
            )
            log_step("clean MX start")
            mx_count = clean_scope(conn, "mx", new_only=new_only, run_id=run_id)
            log_step(f"clean MX done phones={mx_count}")
            log_step("clean CN/KR/GLOBAL start")
            origin_count = clean_scope(conn, "origin", new_only=new_only, run_id=run_id, origin_current_fallback=True)
            log_step(f"clean CN/KR/GLOBAL done phones={origin_count}")
            log_step("mark non-phone start")
            ignored_count = mark_non_phone_records(conn)
            log_step(f"mark non-phone done ignored={ignored_count}")
            log_step("compare candidates start")
            candidate_count = compare_and_clean_candidates(conn)
            log_step(f"compare candidates done candidates={candidate_count}")
            log_step("fill/enrich images and prices start")
            image_count = db.fill_missing_images(conn)
            image_enrich_count = enrich_missing_images(conn, timeout=args.timeout, limit=160)
            price_enrich_count = enrich_missing_prices(conn, timeout=args.timeout, limit=160)
            log_step(f"fill/enrich done image_fill={image_count} image_enrich={image_enrich_count} price_enrich={price_enrich_count}")
            log_step("restore statuses / cleanup / sync business tables start")
            restored_count = db.restore_sampling_statuses(conn, status_snapshot)
            cleanup_counts = db.cleanup_stale_unopened(conn, months=args.retention_months)
            business_counts = db.refresh_business_tables(conn)
            db.finish_run(conn, run_id, utc_now())
            log_step("database work done")
    except Exception:
        print("[ERROR] collect failed", flush=True)
        traceback.print_exc()
        raise

    log_step("export html start")
    output = export_html(args.db, args.export_out)
    print(f"run_id={run_id}")
    for key, count in counts.items():
        print(f"{key}: raw_items +{count}")
    print(f"MX phones: {mx_count}")
    print(f"CN/KR phones: {origin_count}")
    print(f"candidates: {candidate_count}")
    print(f"ignored_non_phone: {ignored_count}")
    print(f"image_fill: {image_count}")
    print(f"image_enrich: {image_enrich_count}")
    print(f"price_enrich: {price_enrich_count}")
    print(f"status_restored: {restored_count}")
    print(
        "cleanup_stale: "
        f"phones {cleanup_counts.get('phones', 0)}, "
        f"candidates {cleanup_counts.get('candidates', 0)}, "
        f"raw_items {cleanup_counts.get('raw_items', 0)}, "
        f"cutoff {cleanup_counts.get('cutoff')}"
    )
    print(f"business_tables: {business_counts}")
    print(f"export_html: {output}")
    log_step("collect command done")


def command_collect_news(args: argparse.Namespace) -> None:
    result = collect_news_once(
        args.db,
        news_config=args.news_config,
        brand=args.brand,
        source_type=args.source_type,
        timeout=args.timeout,
        render_mode=args.render_mode,
        allow_render_fallback=not args.no_render_fallback,
        now=args.now,
    )
    counts = result["counts"]

    print(f"news_window: start={result['window_start']} end={result['window_end']}")
    print(
        "collect-news: "
        f"sources={counts.get('sources', 0)} "
        f"fetched={counts.get('fetched', 0)} "
        f"parsed={counts.get('parsed', 0)} "
        f"inserted={counts.get('inserted', 0)} "
        f"errors={counts.get('errors', 0)} "
        f"rendered={counts.get('rendered', 0)} "
        f"render_errors={counts.get('render_errors', 0)} "
        f"fallbacks={counts.get('fallbacks', 0)} "
        f"detail_fetched={counts.get('detail_fetched', 0)} "
        f"detail_errors={counts.get('detail_errors', 0)}"
    )
    print(f"news_cleanup: deleted={result['cleanup_deleted']} retention_days={result['retention_days']}")


def command_serve(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    run_server(args.db, host=args.host, port=args.port)


def command_export_html(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    output = export_html(args.db, args.out)
    print(f"本地查看页已导出: {output}")


def command_reset_pending(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        counts = db.reset_pending_to_unreviewed(conn)
    print(f"已重置: phones {counts.get('phones', 0)}, candidates {counts.get('candidates', 0)}")


def command_cleanup_stale(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        counts = db.cleanup_stale_unopened(conn, months=args.months)
    print(
        f"cleanup_stale: phones {counts.get('phones', 0)}, candidates {counts.get('candidates', 0)}, "
        f"raw_items {counts.get('raw_items', 0)}, cutoff {counts.get('cutoff')}"
    )


def command_sync_business_tables(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        counts = db.refresh_business_tables(conn)
    print(f"business_tables: {counts}")


def command_sync_dingtalk(args: argparse.Namespace) -> None:
    if os.getenv("PHONE_WATCH_DINGTALK_WRITE_ENABLED", "false").lower() != "true":
        raise RuntimeError("DingTalk writes are disabled (PHONE_WATCH_DINGTALK_WRITE_ENABLED=false)")
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        seen_date = db.latest_collected_date(conn) if args.latest_date else args.seen_date
        counts = sync_rows_to_dingtalk(
            conn,
            config=load_dingtalk_config(),
            source_table=args.source_table,
            status=args.status,
            seen_date=seen_date,
            limit=args.limit,
            dry_run=args.dry_run,
            timeout=args.timeout,
            model_field=args.model_field,
            price_field=args.price_field,
            page_field=args.page_field,
            sales_channel_field=args.sales_channel_field,
        )
    print(f"dingtalk_sync: {counts}")


def command_serve_dingtalk(args: argparse.Namespace) -> None:
    run_dingtalk_server(host=args.host, port=args.port)


def command_rebuild_derived(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        status_snapshot = db.snapshot_sampling_statuses(conn)
        db.clear_derived_tables(conn)
        mx_count = clean_scope(conn, "mx", new_only=args.new_only, today_only=args.today_only)
        origin_count = clean_scope(
            conn,
            "origin",
            new_only=args.new_only,
            today_only=args.today_only,
            origin_current_fallback=True,
        )
        ignored_count = mark_non_phone_records(conn)
        candidate_count = compare_and_clean_candidates(conn)
        image_count = db.fill_missing_images(conn)
        restored_count = db.restore_sampling_statuses(conn, status_snapshot)
    print(f"已重建: MX {mx_count}, CN/KR {origin_count}, candidates {candidate_count}, 非手机忽略 {ignored_count}, 图片回填 {image_count}")


def command_enrich_images(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        updated = enrich_missing_images(conn, timeout=args.timeout, limit=args.limit)
    print(f"图片补全完成: {updated}")


def command_enrich_prices(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    with db.connect(args.db) as conn:
        updated = enrich_missing_prices(conn, timeout=args.timeout, limit=args.limit)
    print(f"价格补全完成: {updated}")


def command_start_server(args: argparse.Namespace) -> None:
    db.init_db(args.db)
    pid = start_background(
        db_path=args.db,
        host=args.host,
        port=args.port,
        log_path=args.log,
        pid_path=args.pid,
    )
    print(f"后台服务已启动: http://{args.host}:{args.port} pid={pid}")


def command_schedule(args: argparse.Namespace) -> None:
    if not 0 <= args.hour <= 23 or not 0 <= args.minute <= 59:
        raise ValueError("hour must be 0-23 and minute must be 0-59")
    db.init_db(args.db)
    run_daily(args.db, hour=args.hour, minute=args.minute)


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    commands = {
        "init-db": command_init_db,
        "check-db": command_check_db,
        "crawl": command_crawl,
        "clean": command_clean,
        "compare": command_compare,
        "pipeline": command_pipeline,
        "collect": command_collect,
        "collect-news": command_collect_news,
        "serve": command_serve,
        "schedule": command_schedule,
        "export-html": command_export_html,
        "reset-pending": command_reset_pending,
        "cleanup-stale": command_cleanup_stale,
        "sync-business-tables": command_sync_business_tables,
        "sync-dingtalk": command_sync_dingtalk,
        "serve-dingtalk": command_serve_dingtalk,
        "rebuild-derived": command_rebuild_derived,
        "enrich-images": command_enrich_images,
        "enrich-prices": command_enrich_prices,
        "start-server": command_start_server,
    }
    commands[args.command](args)
