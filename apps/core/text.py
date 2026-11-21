import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

_APOS = str.maketrans({"’": "'", "ʼ": "'", "`": "'", "‘": "'", "ё": "е"})
_TRACKING = re.compile(r"^(utm_|fbclid$|gclid$|yclid$|mc_|_ga$|ref$)")


def norm_key(s: str) -> str:
    """Matching key for names: lower case, unified apostrophes, no punctuation, single spaces."""
    s = unicodedata.normalize("NFC", (s or "")).lower().translate(_APOS)
    s = re.sub(r"^(м\.|г\.|місто|город|city of)\s*", "", s.strip())
    s = re.sub(r"[^\w' -]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_url(url: str) -> str:
    """Normalised URL for de-duplication: https, no www, no fragment, no tracking params, no trailing slash."""
    url = (url or "").strip()
    if not url:
        return ""
    if "://" not in url:
        url = "https://" + url
    p = urlsplit(url)
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    q = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not _TRACKING.match(k.lower())))
    path = p.path.rstrip("/")
    return urlunsplit(("https", host, path, q, ""))
