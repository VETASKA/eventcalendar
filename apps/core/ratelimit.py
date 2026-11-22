"""Small per-IP limits for public forms (error reports, registration, claims)."""
import hashlib

from django.conf import settings
from django.core.cache import cache


def client_ip(request) -> str:
    # Caddy is the only thing in front of the app and sets X-Forwarded-For; the first entry is the visitor
    fwd = request.META.get("HTTP_X_FORWARDED_FOR", "")
    return (fwd.split(",")[0].strip() if fwd else request.META.get("REMOTE_ADDR", "")) or "unknown"


def ip_hash(request) -> str:
    return hashlib.sha256((settings.SECRET_KEY + client_ip(request)).encode()).hexdigest()


def allow(request, action: str, limit: int, per_seconds: int = 3600) -> bool:
    """True while this IP has made fewer than `limit` `action`s in the window."""
    key = f"rl:{action}:{ip_hash(request)[:32]}"
    if cache.add(key, 1, per_seconds):
        return True
    try:
        n = cache.incr(key)
    except ValueError:            # expired between add and incr
        cache.add(key, 1, per_seconds)
        return True
    return n <= limit
