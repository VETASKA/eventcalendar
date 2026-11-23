"""Sending through the delivery journal: one Delivery per idempotency key, so a retried task never sends twice."""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.template import TemplateDoesNotExist
from django.utils import timezone, translation

from apps.core.i18n import lurl
from apps.core.mail import site_url

from . import telegram
from .models import Delivery, Subscription
from .tokens import unsubscribe_token

logger = logging.getLogger(__name__)


def render(name: str, ctx: dict, lang: str) -> tuple[str, str, str | None]:
    """(subject, text, html) from templates/email/<name>.txt (first line = subject) and optional .html."""
    with translation.override(lang):
        text = render_to_string(f"email/{name}.txt", ctx).strip()
        try:
            html = render_to_string(f"email/{name}.html", ctx)
        except TemplateDoesNotExist:
            html = None
    subject, _, body = text.partition("\n")
    return subject.strip(), body.strip(), html


def deliver(sub: Subscription, kind: str, key: str, template: str, ctx: dict) -> Delivery:
    """Send once. Re-checks the subscription right before sending: an unsubscribe always wins."""
    d, created = Delivery.objects.get_or_create(idempotency_key=key[:120], defaults={"subscription": sub, "kind": kind})
    if d.status == "sent":
        return d
    sub.refresh_from_db(fields=["status", "address"])
    if sub.status != "active" and kind != "confirm":
        d.status, d.error = "failed", "subscription not active"
        d.save(update_fields=["status", "error"])
        return d
    unsub = site_url(sub.site, lurl(f"/unsubscribe/{unsubscribe_token(sub)}/", sub.lang))
    subject, text, html = render(template, {**ctx, "unsubscribe": unsub, "sub": sub}, sub.lang)
    d.attempts += 1
    try:
        if sub.channel == "email":
            msg = EmailMultiAlternatives(subject, text + "\n", settings.DEFAULT_FROM_EMAIL, [sub.address], headers={
                "List-Unsubscribe": f"<{unsub}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"})
            if html:
                msg.attach_alternative(html, "text/html")
            msg.send()
        elif sub.channel == "telegram":
            if not telegram.enabled():
                raise RuntimeError("telegram bot is not configured")
            d.provider_id = telegram.send_message(sub.address, f"{subject}\n\n{text}")
        d.status, d.sent_at, d.error = "sent", timezone.now(), ""
    except Exception as e:  # noqa: BLE001
        logger.warning("delivery %s failed: %s", key, e)
        d.status, d.error = "failed", str(e)[:500]
    d.save()
    return d
