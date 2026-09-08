#!/usr/bin/env python3
"""Validate the configured DeepSeek credential before production is changed."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


MAX_ATTEMPTS = 3
VISION_PIXEL = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAEAAAABACAIAAAAlC+aJAAAAfElEQVR4nNXOQREAIADDsFL/nocIHlyjIGcbZRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncRIncf4OvLpyqgN9ZSiDcwAAAABJRU5ErkJggg=="


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
                {"role": "system", "content": "Return one JSON object and do not call tools."},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Confirm that an image was received as JSON."},
                        {"type": "image_url", "image_url": {"url": VISION_PIXEL}},
                    ],
                },
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "max_tokens": 128,
            "temperature": 0,
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
        raise SystemExit(f"DeepSeek vision preflight failed with HTTP {error.code}") from error
    except (OSError, ValueError) as error:
        raise SystemExit(f"DeepSeek vision preflight failed: {type(error).__name__}") from error
    vision_content = ((vision_result.get("choices") or [{}])[0].get("message") or {}).get("content")
    if not str(vision_content or "").strip():
        raise SystemExit("DeepSeek vision preflight returned no content")
    print(f"DeepSeek preflight OK: text={model}, vision={vision_model}")


if __name__ == "__main__":
    main()
