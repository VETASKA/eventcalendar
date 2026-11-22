"""Language helpers for the public site: Ukrainian has no URL prefix, English and Polish have /en/ and /pl/."""
from django.conf import settings
from django.utils import translation

PUBLIC_LANGS = [code for code, _ in settings.LANGUAGES]


def lang() -> str:
    code = (translation.get_language() or settings.LANGUAGE_CODE)[:2]
    return code if code in PUBLIC_LANGS else settings.LANGUAGE_CODE


def prefix(code: str | None = None) -> str:
    code = code or lang()
    return "" if code == settings.LANGUAGE_CODE else f"/{code}"


def lurl(path: str, code: str | None = None) -> str:
    """'/cabinet/' → '/en/cabinet/' when English is active."""
    return prefix(code) + path


def name_in(names: dict, code: str | None = None, fallback: str = "") -> str:
    code = code or lang()
    return names.get(code) or names.get(settings.LANGUAGE_CODE) or fallback


def context(request):
    """Template context: lp = current language prefix, lang, the language switcher."""
    from django.urls import translate_url

    code = lang()
    full = request.get_full_path()
    switch = []
    if not request.path.startswith(("/admin/", "/api/")):
        for c, label in [("uk", "UA"), ("en", "EN"), ("pl", "PL")]:
            switch.append({"code": c, "label": label, "url": translate_url(full, c), "active": c == code})
    site = getattr(request, "site", None)
    site_name = name_in(site.names, code, site.name) if site else ""
    return {"lp": prefix(code), "lang": code, "lang_switch": switch, "site_name": site_name}
