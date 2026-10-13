"""Generate a byte-preserving maintenance candidate for the existing host vhost."""

import argparse
import json
from pathlib import Path
import sys

MARKER = "/run/deeplinkerp-main-maintenance.on"
MESSAGE = "系统更新中，请稍后再试。当前页面输入不会自动清除，请勿重复提交。"
SERVER_HEADER = b"server {\n    server_name deeplinkerp.com *.deeplinkerp.com;\n"
HTTP_MAPS = f"""# BEGIN deeplinkerp_main_maintenance maps
map $host $deeplinkerp_main_maintenance_marker {{
    default "";
    deeplinkerp.com {MARKER};
}}
map $http_accept $deeplinkerp_main_maintenance_location {{
    default @deeplinkerp_main_maintenance_html;
    ~*application/json @deeplinkerp_main_maintenance_json;
}}
# END deeplinkerp_main_maintenance maps

""".encode()


def _nginx_string(value):
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


_JSON_BODY = json.dumps({
    "exc_type": "SessionStopped",
    "_server_messages": json.dumps([json.dumps({
        "message": MESSAGE, "title": "系统更新中", "indicator": "orange",
    }, ensure_ascii=False)], ensure_ascii=False),
}, ensure_ascii=False)
_HTML_BODY = f'<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>系统更新中</title><body><main><h1>系统更新中</h1><p>{MESSAGE}</p></main></body></html>'
SERVER_GATE = f"""
    # BEGIN deeplinkerp_main_maintenance gate
    if (-f $deeplinkerp_main_maintenance_marker) {{ return 598; }}
    error_page 598 = $deeplinkerp_main_maintenance_location;
    location @deeplinkerp_main_maintenance_html {{
        default_type text/html;
        charset utf-8;
        add_header Retry-After 60 always;
        add_header Cache-Control no-store always;
        return 503 {_nginx_string(_HTML_BODY)};
    }}
    location @deeplinkerp_main_maintenance_json {{
        default_type application/json;
        charset utf-8;
        add_header Retry-After 60 always;
        add_header Cache-Control no-store always;
        return 503 {_nginx_string(_JSON_BODY)};
    }}
    # END deeplinkerp_main_maintenance gate
""".encode()


def patch_main_nginx(source: bytes) -> bytes:
    """Patch only the known two-server layout; reject partial or drifted installs."""
    if source.startswith(HTTP_MAPS):
        original = source[len(HTTP_MAPS):]
        if original.count(SERVER_GATE) != 1 or not original.startswith(SERVER_HEADER + SERVER_GATE):
            raise ValueError("Partial or modified maintenance gate")
        original = SERVER_HEADER + original[len(SERVER_HEADER + SERVER_GATE):]
        if patch_main_nginx(original) != source:
            raise ValueError("Modified maintenance installation")
        return source
    if b"deeplinkerp_main_maintenance" in source or b"return 598;" in source or b"error_page 598" in source:
        raise ValueError("Partial or modified maintenance installation")
    parts = source.split(b"\n}\n")
    if not source.startswith(SERVER_HEADER) or len(parts) != 3 or parts[2] or source.count(b"server {") != 2:
        raise ValueError("Unknown or ambiguous host vhost layout")
    main, redirect = parts[:2]
    required = (
        b"location = /api/v1/mes/stock-entries {",
        b"location = /api/v1/crm/sales-order {",
        b"location / {\n        proxy_pass http://127.0.0.1:8888;",
        b"listen 443 ssl;",
    )
    if (any(main.count(item) != 1 for item in required)
        or main.count(b"proxy_pass http://127.0.0.1:8888") != 3
        or main.count(b"server_name ") != 1 or main.count(b"listen ") != 1
        or not redirect.lstrip(b"\n").startswith(b"server {\n")
        or redirect.count(b"server_name deeplinkerp.com *.deeplinkerp.com;") != 1
        or redirect.count(b"listen 80;") != 1 or redirect.count(b"listen ") != 1
        or b"return 301 https://$host$request_uri;" not in redirect):
        raise ValueError("Unknown or ambiguous main HTTPS/HTTP server shape")
    return HTTP_MAPS + SERVER_HEADER + SERVER_GATE + source[len(SERVER_HEADER):]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    args = parser.parse_args()
    try:
        candidate = patch_main_nginx(args.source.read_bytes())
    except ValueError as error:
        parser.error(str(error))
    sys.stdout.buffer.write(candidate)
