#!/usr/bin/env python3
"""Validate the configured DeepSeek credential before production is changed."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request


MAX_ATTEMPTS = 3


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


def main() -> None:
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing DEEPSEEK_API_KEY")
    base_url = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com").rstrip("/")
    model = os.environ.get("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()
    for attempt in range(1, MAX_ATTEMPTS + 1):
        request = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=_request_payload(model, attempt),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise SystemExit(f"DeepSeek preflight failed with HTTP {error.code}") from error
        except (OSError, ValueError) as error:
            raise SystemExit(f"DeepSeek preflight failed: {type(error).__name__}") from error
        content = ((result.get("choices") or [{}])[0].get("message") or {}).get("content")
        if str(content or "").strip():
            break
    else:
        raise SystemExit(f"DeepSeek preflight returned no content after {MAX_ATTEMPTS} attempts")
    print(f"DeepSeek preflight OK: {model}")


if __name__ == "__main__":
    main()
