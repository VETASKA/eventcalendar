"""Sending mail in the reader's language from templates/email/<name>.txt (+ optional .html).

The first line of the .txt template is the subject. Links in mail must be absolute: use site_url().
"""
import logging

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template import TemplateDoesNotExist
from django.template.loader import render_to_string
from django.utils import translation

logger = logging.getLogger(__name__)


def site_url(site, path: str = "/") -> str:
    """https://<primary domain><path> for a storefront (used where there is no request, e.g. Celery)."""
    d = site.domains.order_by("-is_primary", "id").first() if site else None
    host = d.host if d else "localhost:8000"
    scheme = "http" if host.startswith(("localhost", "127.")) else "https"
    return f"{scheme}://{host}{path}"


def send(to: str, name: str, context: dict, *, lang: str = "uk", headers: dict | None = None) -> bool:
    """Returns True when handed to the mail server. Never raises: a broken SMTP must not break a page."""
    with translation.override(lang):
        text = render_to_string(f"email/{name}.txt", context).strip()
        try:
            html = render_to_string(f"email/{name}.html", context)
        except TemplateDoesNotExist:
            html = None
    subject, _, body = text.partition("\n")
    msg = EmailMultiAlternatives(subject.strip(), body.strip() + "\n", settings.DEFAULT_FROM_EMAIL, [to],
                                 headers=headers or {})
    if html:
        msg.attach_alternative(html, "text/html")
    try:
        msg.send()
        return True
    except Exception:  # noqa: BLE001 — logged; the caller decides what to tell the person
        logger.exception("mail to %s (%s) failed", to, name)
        return False
