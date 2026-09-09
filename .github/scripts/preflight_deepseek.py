#!/usr/bin/env python3
"""Validate the configured DeepSeek credential before production is changed."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


MAX_ATTEMPTS = 3
VISION_PIXEL = "data:image/jpeg;base64,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"


def _request_payload(model: str, attempt: int) -> bytes:
    return json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "Return only one JSON object. Example: "
                        '{"health_check":true,"attempt":1}'
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"health_check": True, "attempt": attempt},
                        separators=(",", ":"),
                    ),
                },
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": 128,
            "temperature": 0,
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _vision_request_payload(model: str) -> bytes:
    return json.dumps(
        {
            "model": model,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "What is in this image?"},
                        {"type": "image_url", "image_url": {"url": VISION_PIXEL}},
                    ],
                },
            ],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _call(base_url: str, api_key: str, body: bytes) -> dict:
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _http_error_detail(error: urllib.error.HTTPError) -> str:
    try:
        payload = json.loads(error.read().decode("utf-8", errors="replace"))
        detail = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(detail, dict):
            return str(detail.get("message") or detail.get("code") or detail.get("type") or "")[:300]
    except (OSError, TypeError, ValueError):
        return ""
    return ""


def main() -> None:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    vision_model = os.environ.get("DEEPSEEK_VISION_MODEL", "deepseek-v4-flash-vision-exp").strip()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = _call(base_url, api_key, _request_payload(model, attempt))
        except urllib.error.HTTPError as error:
            raise SystemExit(f"DeepSeek preflight failed with HTTP {error.code}") from error
        except (OSError, ValueError) as error:
            raise SystemExit(f"DeepSeek preflight failed: {type(error).__name__}") from error
        content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
        if str(content or "").strip():
            break
    else:
        raise SystemExit(f"DeepSeek preflight returned no content after {MAX_ATTEMPTS} attempts")
    try:
        vision_result = _call(base_url, api_key, _vision_request_payload(vision_model))
    except urllib.error.HTTPError as error:
        detail = _http_error_detail(error)
        raise SystemExit(
            f"DeepSeek vision preflight failed with HTTP {error.code}"
            + (f": {detail}" if detail else "")
        ) from error
    except (OSError, ValueError) as error:
        raise SystemExit(f"DeepSeek vision preflight failed: {type(error).__name__}") from error
    vision_content = ((vision_result.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not str(vision_content or "").strip():
        raise SystemExit("DeepSeek vision preflight returned no content")
    print(f"DeepSeek preflight OK: text={model}, vision={vision_model}")


if __name__ == "__main__":
    main()
