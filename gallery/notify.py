"""Doorbell notification: pings Telegram when a new decision request is posted.

Uses the Telegram Bot API directly over stdlib urllib (no extra dependency,
no subprocess). Must never block or fail the request that triggered it —
callers fire this in a background thread and any error is just logged.
"""

import json
import logging
import urllib.request

log = logging.getLogger("gallery.notify")

TELEGRAM_TIMEOUT = 10


def send_doorbell(cfg: dict, title: str, variant_count: int, url_with_token: str) -> None:
    from . import config as config_mod

    bot_token, chat_id = config_mod.telegram_creds(cfg)
    if not bot_token or not chat_id:
        log.info("doorbell skipped: telegram_bot_token/chat_id not configured")
        return

    text = f"\U0001f5bc {title} ({variant_count} variants) — {url_with_token}"
    payload = json.dumps({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TELEGRAM_TIMEOUT) as resp:
            if resp.status >= 300:
                log.warning("doorbell failed: telegram returned status %s", resp.status)
    except Exception as exc:  # noqa: BLE001 - notification must never break the request
        log.warning("doorbell failed: %s", exc)
