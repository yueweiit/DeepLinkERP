#!/usr/bin/env python3
"""Benchmark the MES Material Request HTTP endpoint.

This script deliberately uses only Python's standard library. Run it from the
ERPNext host, preferably against 127.0.0.1, to keep WAN/MES network latency out
of the baseline. It queues requests that create and submit real Material Requests, so use a
dedicated test company, item, and warehouse.

Example::

    MES_API_AUTHORIZATION='token <api_key>:<api_secret>' \
    python3 scripts/benchmark_material_request_api.py \
        --base-url http://127.0.0.1:8000 \
        --host-header dev.localhost \
        --company 'Test Company' \
        --item-code 'TEST-ITEM' \
        --warehouse 'Stores - TC' \
        --uom Nos \
        --detail-count 5000 \
        --requests 5 \
        --workers 1 \
        --warmup 1 \
        --confirm

The reported latency is client-observed HTTP round-trip time, including the
request body upload and response body read. Payload generation and warm-up
requests are excluded from the measured samples.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import date
from http.client import HTTPConnection, HTTPSConnection
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


DEFAULT_ENDPOINT_PATH = "/api/method/mes_integration.api.create_material_request"
DEFAULT_TIMEOUT_SECONDS = 180.0
MAX_ERROR_LENGTH = 300
SERVER_OWNED_DETAIL_FIELDS = {
    "doctype",
    "docstatus",
    "idx",
    "name",
    "parent",
    "parentfield",
    "parenttype",
    "material_request_item",
}


@dataclass(frozen=True)
class Endpoint:
    scheme: str
    host: str
    port: int | None
    path: str
    host_header: str
    timeout: float
    insecure: bool


@dataclass
class Sample:
    index: int
    ok: bool
    elapsed_ms: float
    http_status: int | None = None
    task_id: str | None = None
    material_request: str | None = None
    error: str | None = None


class ConnectionPool:
    """Keep one HTTP connection per worker so TCP setup is not in every sample."""

    def __init__(self, endpoint: Endpoint):
        self.endpoint = endpoint
        self.local = threading.local()
        self.connections: list[HTTPConnection | HTTPSConnection] = []
        self.lock = threading.Lock()

    def get(self) -> HTTPConnection | HTTPSConnection:
        connection = getattr(self.local, "connection", None)
        if connection is None:
            if self.endpoint.scheme == "https":
                context = ssl._create_unverified_context() if self.endpoint.insecure else None
                connection = HTTPSConnection(
                    self.endpoint.host,
                    self.endpoint.port,
                    timeout=self.endpoint.timeout,
                    context=context,
                )
            else:
                connection = HTTPConnection(
                    self.endpoint.host,
                    self.endpoint.port,
                    timeout=self.endpoint.timeout,
                )

            self.local.connection = connection
            with self.lock:
                self.connections.append(connection)

        return connection

    def close(self) -> None:
        with self.lock:
            connections = list(self.connections)
            self.connections.clear()

        for connection in connections:
            connection.close()

    def discard(self, connection: HTTPConnection | HTTPSConnection) -> None:
        connection.close()
        if getattr(self.local, "connection", None) is connection:
            del self.local.connection
        with self.lock:
            if connection in self.connections:
                self.connections.remove(connection)


def build_payload(args: argparse.Namespace) -> dict[str, Any]:
    detail_count = args.detail_count
    detail_template = load_detail_template(args.detail_template_file)
    item = {
        "item_code": args.item_code,
        "qty": max(detail_count, 1),
        "uom": args.uom,
        "stock_uom": args.uom,
        "conversion_factor": 1,
        "warehouse": args.warehouse,
        "schedule_date": date.today().isoformat(),
    }

    details = [
        {
            **detail_template,
            "material_request_item_idx": 1,
            "item_code": args.item_code,
            "order_qty": 1,
            "issue_qty": 1,
            "uom": args.uom,
        }
        for _ in range(detail_count)
    ]

    return {
        "material_request": {
            "doctype": "Material Request",
            "material_request_type": args.material_request_type,
            "company": args.company,
            "items": [item],
            "custom_item_details": details,
        }
    }


def load_detail_template(path: Path | None) -> dict[str, Any]:
    if not path:
        return {}

    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取 --detail-template-file: {exc}") from exc

    if not isinstance(value, dict):
        raise ValueError("--detail-template-file 必须是一个 JSON 对象")

    return {
        key: item_value
        for key, item_value in value.items()
        if key not in SERVER_OWNED_DETAIL_FIELDS
    }


def build_endpoint(args: argparse.Namespace) -> Endpoint:
    parsed = urlsplit(args.base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--base-url 必须是完整的 http:// 或 https:// 地址")

    base_path = parsed.path.rstrip("/")
    endpoint_path = args.endpoint_path.strip()
    if not endpoint_path.startswith("/"):
        endpoint_path = f"/{endpoint_path}"

    path = f"{base_path}{endpoint_path}" or "/"
    if parsed.query:
        path = f"{path}?{parsed.query}"

    host_header = args.host_header or parsed.hostname
    if parsed.port and not args.host_header:
        host_header = f"{host_header}:{parsed.port}"

    return Endpoint(
        scheme=parsed.scheme,
        host=parsed.hostname,
        port=parsed.port,
        path=path,
        host_header=host_header,
        timeout=args.timeout,
        insecure=args.insecure,
    )


def normalize_authorization(value: str | None) -> str | None:
    if not value:
        return None

    value = value.strip()
    if not value:
        return None

    if value.lower().startswith(("token ", "bearer ")):
        return value

    return f"token {value}"


def post_json(
    endpoint: Endpoint,
    pool: ConnectionPool,
    body: bytes,
    authorization: str,
) -> tuple[int, bytes]:
    headers = {
        "Accept": "application/json",
        "Authorization": authorization,
        "Connection": "keep-alive",
        "Content-Length": str(len(body)),
        "Content-Type": "application/json",
        "Host": endpoint.host_header,
        "User-Agent": "mes-material-request-benchmark/1.0",
    }

    connection = pool.get()
    try:
        connection.request("POST", endpoint.path, body=body, headers=headers)
        response = connection.getresponse()
        return response.status, response.read()
    except Exception:
        # A broken keep-alive connection must not poison the next sample.
        pool.discard(connection)
        raise


def run_one(
    index: int,
    endpoint: Endpoint,
    pool: ConnectionPool,
    body: bytes,
    authorization: str,
    interval_ms: float,
) -> Sample:
    if interval_ms:
        time.sleep(interval_ms / 1000)

    started = time.perf_counter_ns()
    try:
        status, raw_response = post_json(endpoint, pool, body, authorization)
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        response_data = parse_json_response(raw_response)
        ok, task_id, material_request, error = validate_response(status, response_data)
        return Sample(
            index=index,
            ok=ok,
            elapsed_ms=elapsed_ms,
            http_status=status,
            task_id=task_id,
            material_request=material_request,
            error=error,
        )
    except Exception as exc:
        elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
        return Sample(
            index=index,
            ok=False,
            elapsed_ms=elapsed_ms,
            error=f"{type(exc).__name__}: {exc}"[:MAX_ERROR_LENGTH],
        )


def parse_json_response(raw_response: bytes) -> Any:
    try:
        return json.loads(raw_response.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None


def validate_response(
    status: int, response_data: Any
) -> tuple[bool, str | None, str | None, str | None]:
    if not isinstance(response_data, dict):
        return False, None, None, f"HTTP {status}: 返回不是 JSON"

    data = response_data.get("data")
    if not isinstance(data, dict):
        message = response_data.get("message")
        data = message if isinstance(message, dict) else {}

    task_id = data.get("task_id")
    material_request = data.get("material_request")
    if (
        200 <= status < 300
        and data.get("status") in {"queued", "processing", "success"}
        and task_id
    ):
        return True, task_id, material_request, None

    error = (
        response_data.get("exception")
        or response_data.get("exc_type")
        or response_data.get("_server_messages")
        or data.get("message")
        or f"HTTP {status}"
    )
    return False, task_id, material_request, str(error).replace("\n", " ")[:MAX_ERROR_LENGTH]


def run_batch(
    count: int,
    workers: int,
    endpoint: Endpoint,
    body: bytes,
    authorization: str,
    interval_ms: float,
    pool: ConnectionPool | None = None,
    executor: ThreadPoolExecutor | None = None,
) -> list[Sample]:
    owns_pool = pool is None
    pool = pool or ConnectionPool(endpoint)
    owns_executor = executor is None
    executor = executor or ThreadPoolExecutor(
        max_workers=workers,
        thread_name_prefix="mes-benchmark",
    )
    try:
        futures = [
            executor.submit(
                run_one,
                index,
                endpoint,
                pool,
                body,
                authorization,
                interval_ms,
            )
            for index in range(1, count + 1)
        ]
        samples = [future.result() for future in as_completed(futures)]
    finally:
        if owns_executor:
            executor.shutdown(wait=True)
        if owns_pool:
            pool.close()

    return sorted(samples, key=lambda sample: sample.index)


def percentile(values: list[float], percentile_value: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]

    position = (len(values) - 1) * percentile_value / 100
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] + (values[upper] - values[lower]) * fraction


def summarize(samples: list[Sample], wall_time_ms: float) -> dict[str, Any]:
    successful = [sample.elapsed_ms for sample in samples if sample.ok]
    latencies = sorted(sample.elapsed_ms for sample in samples)
    summary = {
        "total": len(samples),
        "success": len(successful),
        "failed": len(samples) - len(successful),
        "wall_time_ms": round(wall_time_ms, 2),
        "throughput_requests_per_second": round(
            len(samples) / (wall_time_ms / 1000), 3
        )
        if wall_time_ms
        else 0,
        "latency_ms": {
            "min": round(min(successful), 2) if successful else 0,
            "avg": round(sum(successful) / len(successful), 2) if successful else 0,
            "p50": round(percentile(sorted(successful), 50), 2),
            "p95": round(percentile(sorted(successful), 95), 2),
            "p99": round(percentile(sorted(successful), 99), 2),
            "max": round(max(successful), 2) if successful else 0,
        },
    }
    if latencies and not successful:
        summary["latency_ms"]["failed_min"] = round(latencies[0], 2)
        summary["latency_ms"]["failed_max"] = round(latencies[-1], 2)
    return summary


def print_report(
    args: argparse.Namespace,
    body_size: int,
    warmup_count: int,
    samples: list[Sample],
    summary: dict[str, Any],
) -> None:
    print("\nMES Material Request 接口压测结果")
    print(f"请求数: {args.requests}，并发数: {args.workers}，明细数: {args.detail_count}")
    print(f"请求体大小: {body_size / 1024:.2f} KiB，预热请求: {warmup_count}")
    print(
        "成功/失败: "
        f"{summary['success']}/{summary['failed']}，"
        f"总耗时: {summary['wall_time_ms']:.2f} ms，"
        f"吞吐: {summary['throughput_requests_per_second']:.3f} req/s"
    )

    latency = summary["latency_ms"]
    print(
        "成功请求耗时(ms): "
        f"min={latency['min']:.2f}, avg={latency['avg']:.2f}, "
        f"p50={latency['p50']:.2f}, p95={latency['p95']:.2f}, "
        f"p99={latency['p99']:.2f}, max={latency['max']:.2f}"
    )

    failures = [sample for sample in samples if not sample.ok]
    for sample in failures[:10]:
        print(
            f"失败 #{sample.index}: HTTP {sample.http_status or '-'}, "
            f"耗时 {sample.elapsed_ms:.2f} ms, {sample.error or '未知错误'}",
            file=sys.stderr,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MES Material Request 接口压测脚本")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="ERP 地址")
    parser.add_argument(
        "--endpoint-path",
        default=DEFAULT_ENDPOINT_PATH,
        help=f"接口路径，默认 {DEFAULT_ENDPOINT_PATH}",
    )
    parser.add_argument(
        "--host-header",
        help="Frappe 站点 Host，例如 dev.localhost；反向代理/多站点时建议显式传入",
    )
    parser.add_argument(
        "--authorization",
        default=os.environ.get("MES_API_AUTHORIZATION") or os.environ.get("MES_API_TOKEN"),
        help="Authorization 值，也可通过 MES_API_AUTHORIZATION 或 MES_API_TOKEN 传入",
    )
    parser.add_argument("--company", required=True, help="测试公司")
    parser.add_argument("--item-code", required=True, help="测试库存物料")
    parser.add_argument("--warehouse", required=True, help="测试非组仓库")
    parser.add_argument("--uom", required=True, help="测试物料的库存单位")
    parser.add_argument(
        "--detail-template-file",
        type=Path,
        help="一条 MES 明细 JSON 样例；会复制到每条明细以模拟生产 payload 大小",
    )
    parser.add_argument(
        "--material-request-type",
        default="Material Issue",
        help="物料需求类型，默认 Material Issue",
    )
    parser.add_argument("--detail-count", type=int, default=5000, help="每单 MES 明细数，默认 5000")
    parser.add_argument("--requests", type=int, default=5, help="正式请求数，默认 5")
    parser.add_argument("--workers", type=int, default=1, help="并发 worker 数，默认 1")
    parser.add_argument("--warmup", type=int, default=1, help="预热请求数，默认 1")
    parser.add_argument(
        "--interval-ms",
        type=float,
        default=0,
        help="每个请求开始前的间隔，单位毫秒，默认 0",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help=f"单请求超时时间，默认 {DEFAULT_TIMEOUT_SECONDS:g} 秒",
    )
    parser.add_argument("--insecure", action="store_true", help="HTTPS 跳过证书校验，仅用于测试环境")
    parser.add_argument(
        "--output",
        type=Path,
        help="将汇总和每条样本保存为 JSON 文件，不保存 Authorization",
    )
    parser.add_argument("--dry-run", action="store_true", help="只生成并检查请求体，不调用接口")
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="确认允许创建并提交测试物料需求；非 dry-run 时必需",
    )
    args = parser.parse_args()

    if args.detail_count < 0:
        parser.error("--detail-count 不能小于 0")
    if args.requests < 1:
        parser.error("--requests 必须大于 0")
    if args.workers < 1:
        parser.error("--workers 必须大于 0")
    if args.warmup < 0:
        parser.error("--warmup 不能小于 0")
    if args.interval_ms < 0 or args.timeout <= 0:
        parser.error("--interval-ms 不能小于 0，--timeout 必须大于 0")
    if not args.dry_run and not args.confirm:
        parser.error("正式压测会创建并提交真实单据，请增加 --confirm；或使用 --dry-run")

    return args


def main() -> int:
    args = parse_args()
    try:
        payload = build_payload(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    print(f"请求体已生成: {len(body) / 1024:.2f} KiB，明细数: {args.detail_count}")
    if args.dry_run:
        print("dry-run：未调用接口，也未创建单据。")
        return 0

    authorization = normalize_authorization(args.authorization)
    if not authorization:
        print(
            "缺少认证信息，请设置 MES_API_AUTHORIZATION 或 MES_API_TOKEN，"
            "或传入 --authorization。",
            file=sys.stderr,
        )
        return 2

    try:
        endpoint = build_endpoint(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    warmup_count = max(args.warmup, args.workers) if args.warmup else 0
    print(
        f"目标: {endpoint.scheme}://{endpoint.host}:{endpoint.port or ''}{endpoint.path}，"
        f"Host: {endpoint.host_header}"
    )
    print("注意：该脚本会创建并提交真实 Material Request，请确认使用的是专用测试数据。")

    pool = ConnectionPool(endpoint)
    executor = ThreadPoolExecutor(max_workers=args.workers, thread_name_prefix="mes-benchmark")
    try:
        if warmup_count:
            print(f"开始预热 {warmup_count} 个请求（不计入统计）...")
            warmup_samples = run_batch(
                warmup_count,
                args.workers,
                endpoint,
                body,
                authorization,
                args.interval_ms,
                pool=pool,
                executor=executor,
            )
            warmup_failures = [sample for sample in warmup_samples if not sample.ok]
            if warmup_failures:
                print("预热请求失败，停止正式压测。", file=sys.stderr)
                for sample in warmup_failures[:10]:
                    print(f"预热 #{sample.index}: {sample.error}", file=sys.stderr)
                return 1

        print(f"开始正式压测 {args.requests} 个请求...")
        started = time.perf_counter_ns()
        samples = run_batch(
            args.requests,
            args.workers,
            endpoint,
            body,
            authorization,
            args.interval_ms,
            pool=pool,
            executor=executor,
        )
        wall_time_ms = (time.perf_counter_ns() - started) / 1_000_000
        summary = summarize(samples, wall_time_ms)
        print_report(args, len(body), warmup_count, samples, summary)
    finally:
        executor.shutdown(wait=True)
        pool.close()

    if args.output:
        result = {
            "config": {
                "base_url": args.base_url,
                "endpoint_path": args.endpoint_path,
                "host_header": endpoint.host_header,
                "company": args.company,
                "item_code": args.item_code,
                "warehouse": args.warehouse,
                "uom": args.uom,
                "material_request_type": args.material_request_type,
                "detail_count": args.detail_count,
                "requests": args.requests,
                "workers": args.workers,
                "warmup": warmup_count,
                "body_size_bytes": len(body),
            },
            "summary": summary,
            "samples": [asdict(sample) for sample in samples],
        }
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已保存: {args.output}")

    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
