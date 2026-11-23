"""Telegram Bot API, the small part we need. Everything is off until TELEGRAM_BOT_TOKEN is set."""
import logging

import httpx
from django.conf import settings

logger = logging.getLogger(__name__)


def enabled() -> bool:
    return bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_BOT_NAME)


def _call(method: str, **params) -> dict:
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/{method}"
    r = httpx.post(url, json=params, timeout=15)
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {"ok": False}
    if not data.get("ok"):
        raise RuntimeError(f"telegram {method}: {data.get('description') or r.status_code}")
    return data["result"]


def send_message(chat_id: str, text: str) -> str:
    """Returns the message id. Raises on failure (the delivery journal records it)."""
    res = _call("sendMessage", chat_id=chat_id, text=text[:4000], disable_web_page_preview=True)
    return str(res.get("message_id", ""))


def set_webhook(url: str) -> None:
    _call("setWebhook", url=url, secret_token=settings.TELEGRAM_WEBHOOK_SECRET or None,
          allowed_updates=["message"], drop_pending_updates=True)


def deep_link(token: str) -> str:
    return f"https://t.me/{settings.TELEGRAM_BOT_NAME}?start={token}"
