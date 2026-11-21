from __future__ import annotations

from django.db.models import Q

from apps.core.text import norm_key

from .models import City


def resolve_city(country_code: str, raw: str) -> tuple[City | None, str]:
    """(city, problem). problem is '' | 'city_unknown' | 'city_ambiguous' (→ moderator)."""
    key = norm_key(raw)
    if not key:
        return None, ""
    qs = City.objects.filter(is_active=True).filter(Q(aliases__key=key) | Q(name__iexact=raw.strip()))
    if country_code:
        qs = qs.filter(country_id=country_code)
    found = list(qs.distinct().order_by("-importance", "id")[:10])
    if not found:
        return None, "city_unknown"
    if len(found) == 1:
        return found[0], ""
    # several places share the name: the clearly most important one (an oblast centre over a village) wins
    if found[0].importance > found[1].importance:
        return found[0], ""
    return None, "city_ambiguous"
