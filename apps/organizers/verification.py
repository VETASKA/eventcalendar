"""Proving control of the event's site (spec §6): a file with a token, or a one-time link to a corporate address.

The host is the event's own site (from the card), never one the person types. A token is tied to one claim,
expires after Claim.TOKEN_DAYS and stops working once used.
"""
import hashlib
import hmac
import secrets
from datetime import timedelta
from urllib.parse import urlsplit

from django.conf import settings
from django.core import signing
from django.utils import timezone

FILE_NAME = "eventcalendar-verify.txt"
PUBLIC_MAIL = {
    "gmail.com", "googlemail.com", "ukr.net", "i.ua", "meta.ua", "bigmir.net", "email.ua", "online.ua",
    "outlook.com", "hotmail.com", "live.com", "msn.com", "yahoo.com", "ymail.com", "icloud.com", "me.com", "mac.com",
    "aol.com", "proton.me", "protonmail.com", "pm.me", "gmx.com", "gmx.net", "gmx.de", "mail.com", "zoho.com",
    "yandex.ru", "yandex.ua", "ya.ru", "mail.ru", "inbox.ru", "list.ru", "bk.ru", "rambler.ru", "tutanota.com",
    "wp.pl", "o2.pl", "onet.pl", "interia.pl", "poczta.fm", "seznam.cz", "fastmail.com", "hey.com",
}


def event_host(event) -> str:
    """The site we will check: the organizer's site if known, otherwise the source page's host."""
    for url in (event.organizer_site, event.source_url):
        host = (urlsplit(url).hostname or "").lower().removeprefix("www.")
        if host:
            return host
    return ""


def file_token(claim) -> str:
    """Stable for one claim (so the page can show it again), different for every claim."""
    raw = f"claim:{claim.pk}:{claim.created_at.isoformat()}:{claim.user_id}"
    return "ec-" + hmac.new(settings.SECRET_KEY.encode(), raw.encode(), hashlib.sha256).hexdigest()[:32]


def token_expired(claim) -> bool:
    return timezone.now() > claim.created_at + timedelta(days=claim.TOKEN_DAYS)


def check_file(claim, fetch=None) -> tuple[bool, str]:
    """(ok, reason). Fetches https://<host>/eventcalendar-verify.txt and looks for this claim's token."""
    from apps.intake.fetcher import safe_fetch

    if claim.status != "open":
        return False, "used"
    if token_expired(claim):
        return False, "expired"
    if not claim.host:
        return False, "no_host"
    r = (fetch or safe_fetch)(f"https://{claim.host}/{FILE_NAME}", allow_text=True)
    if not r.ok:
        return False, "not_found"
    if urlsplit(r.url).hostname and (urlsplit(r.url).hostname.lower().removeprefix("www.") != claim.host):
        return False, "other_host"                       # redirected elsewhere: the file must be on the event's site
    lines = {line.strip() for line in r.html.splitlines()}
    return (True, "ok") if file_token(claim) in lines else (False, "wrong_token")


def corporate_ok(email: str, host: str) -> tuple[bool, str]:
    domain = email.rsplit("@", 1)[-1].lower().strip()
    if domain in PUBLIC_MAIL:
        return False, "public"
    if not host or not (domain == host or host.endswith("." + domain) or domain.endswith("." + host)):
        return False, "other_domain"
    return True, "ok"


def make_email_link_token(claim, email: str) -> str:
    nonce = secrets.token_urlsafe(16)
    claim.token_hash = hashlib.sha256(nonce.encode()).hexdigest()
    claim.verify_email = email
    claim.expires_at = timezone.now() + timedelta(hours=24)
    claim.save(update_fields=["token_hash", "verify_email", "expires_at"])
    return signing.dumps({"c": claim.pk, "n": nonce}, salt="claim-email")


def use_email_link_token(token: str):
    """→ (claim or None, reason). One-time: the stored hash is cleared when used."""
    from .models import Claim

    try:
        data = signing.loads(token, salt="claim-email", max_age=24 * 3600)
    except signing.SignatureExpired:
        return None, "expired"
    except signing.BadSignature:
        return None, "bad"
    claim = Claim.objects.filter(pk=data.get("c")).first()
    if claim is None or claim.status != "open":
        return None, "used"
    if not claim.token_hash or not hmac.compare_digest(claim.token_hash,
                                                       hashlib.sha256(data.get("n", "").encode()).hexdigest()):
        return None, "used"
    return claim, "ok"


def mark_verified(claim, method: str) -> None:
    claim.status, claim.method, claim.verified_at, claim.token_hash = "verified", method, timezone.now(), ""
    claim.save(update_fields=["status", "method", "verified_at", "token_hash"])
