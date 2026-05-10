#!/usr/bin/env python3
"""HTTP GET で API を取得し、本文を Incoming Webhook 経由で Discord または Slack に通知する。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

MAX_BODY_LEN = 1800


def truncate(s: str) -> str:
    if len(s) <= MAX_BODY_LEN:
        return s
    return s[:MAX_BODY_LEN] + "(truncated)"


def main() -> None:
    api_url = os.environ["API_URL"]
    provider = os.environ.get("NOTIFY_PROVIDER", "discord").strip().lower()
    get_timeout = float(os.environ.get("HTTP_GET_TIMEOUT", "60"))
    post_timeout = float(os.environ.get("HTTP_POST_TIMEOUT", "30"))

    req_get = urllib.request.Request(api_url, method="GET")
    try:
        with urllib.request.urlopen(req_get, timeout=get_timeout) as r:
            raw = r.read().decode()
    except urllib.error.HTTPError as e:
        raise SystemExit(f"GET failed: {e.code} {e.reason}") from e
    except OSError as e:
        raise SystemExit(f"GET failed: {e}") from e

    short = truncate(raw)

    if provider == "slack":
        webhook = (os.environ.get("SLACK_WEBHOOK_URL") or "").strip()
        payload = {"text": short}
    elif provider == "discord":
        webhook = (os.environ.get("DISCORD_WEBHOOK_URL") or "").strip()
        payload = {"content": short}
    else:
        raise SystemExit(f"NOTIFY_PROVIDER must be discord or slack, got {provider!r}")

    if not webhook:
        raise SystemExit(f"webhook URL is empty for provider={provider}")

    data = json.dumps(payload).encode()
    req_post = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req_post, timeout=post_timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"POST webhook failed: {e.code} {e.reason}: {body}") from e


if __name__ == "__main__":
    main()
    print("done")
