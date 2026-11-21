"""Import of the official Ukrainian codifier (КАТОТТГ) from the Ministry's XLSX or a CSV export of it.

Columns (row with «Категорія об'єкта» is the header; the rows above it are a title):
  Перший рівень | Другий рівень | Третій рівень | Четвертий рівень | Додатковий рівень | Категорія | Назва
Categories: O область / АРК, K місто зі спецстатусом, P район, H громада, M місто, X (earlier T) селище,
C село, B район у місті (skipped).

Re-import keeps internal IDs: records are matched by official code; a city seeded earlier without a code
(seed_reference) is adopted by its name. Records missing from a new snapshot are deactivated, never deleted.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path

from django.db import transaction

from .models import City, CityAlias, Country, Region

OBLAST_CENTRES = {"Вінниця", "Луцьк", "Дніпро", "Донецьк", "Житомир", "Ужгород", "Запоріжжя", "Івано-Франківськ",
                  "Кропивницький", "Луганськ", "Львів", "Миколаїв", "Одеса", "Полтава", "Рівне", "Суми",
                  "Тернопіль", "Харків", "Херсон", "Хмельницький", "Черкаси", "Чернівці", "Чернігів",
                  "Сімферополь"}
CITY_KIND = {"K": "special", "M": "city", "X": "town", "T": "town", "C": "village"}
IMPORTANCE = {"special": 100, "city": 20, "town": 5, "village": 1}


def _rows(path: Path):
    if path.suffix.lower() in (".xlsx", ".xlsm"):
        from openpyxl import load_workbook
        ws = load_workbook(path, read_only=True, data_only=True).worksheets[0]
        for r in ws.iter_rows(values_only=True):
            yield ["" if v is None else str(v).strip() for v in r]
    else:
        raw = path.read_bytes()
        text = raw.decode("utf-8-sig") if not raw.startswith(b"\xff\xfe") else raw.decode("utf-16")
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,\t")
        for r in csv.reader(io.StringIO(text), dialect):
            yield [c.strip() for c in r]


def _nice(name: str) -> str:
    """Older snapshots spell names in capitals; the official spelling otherwise stays as is."""
    if name.isupper():
        return "-".join(p.capitalize() for p in name.lower().split("-"))
    return name


def read(path: Path) -> list[dict]:
    rows, header = [], None
    for r in _rows(path):
        if header is None:
            if any("атегор" in c for c in r):
                header = r
            continue
        if len(r) < 7 or not any(r[:5]):
            continue
        rows.append({"l1": r[0], "l2": r[1], "l3": r[2], "l4": r[3], "extra": r[4], "cat": r[5].upper()[:1],
                     "name": _nice(r[6])})
    if header is None:
        raise ValueError("не знайдено рядок заголовка з «Категорія»")
    return rows


@transaction.atomic
def import_katottg(path: Path, version: str) -> dict:
    ua, _ = Country.objects.get_or_create(code="UA", defaults={"names": {"uk": "Україна", "en": "Ukraine",
                                                                          "pl": "Ukraina"},
                                                                "timezone": "Europe/Kyiv"})
    stats = {"regions": 0, "cities_new": 0, "cities_updated": 0, "deactivated": 0, "skipped": 0}
    regions: dict[str, Region] = {r.official_code: r for r in Region.objects.filter(country=ua).exclude(official_code="")}

    def region(code, name, level, parent):
        r = regions.get(code)
        if r is None:
            r = Region.objects.create(country=ua, official_code=code, name=name, level=level, parent=parent)
            regions[code] = r
        elif (r.name, r.level, r.parent_id) != (name, level, parent.pk if parent else None):
            r.name, r.level, r.parent = name, level, parent
            r.save()
        stats["regions"] += 1
        return r

    data = read(path)
    seen: set[str] = set()
    for row in data:                                    # 1) the administrative levels
        if row["cat"] == "O":
            region(row["l1"], row["name"], "oblast", None)
    for row in data:
        if row["cat"] == "P":
            region(row["l2"], row["name"], "raion", regions.get(row["l1"]))
    for row in data:
        if row["cat"] == "H":
            region(row["l3"], row["name"], "hromada", regions.get(row["l2"]))

    for row in data:                                    # 2) the places
        kind = CITY_KIND.get(row["cat"])
        if not kind:
            if row["cat"] not in "OPHB":
                stats["skipped"] += 1
            continue
        code = row["l1"] if kind == "special" else (row["l4"] or row["l3"])
        oblast = None if kind == "special" else regions.get(row["l1"])
        hromada = None if kind == "special" else regions.get(row["l3"])
        importance = IMPORTANCE[kind] + (40 if kind == "city" and row["name"] in OBLAST_CENTRES else 0)
        seen.add(code)
        city = City.objects.filter(country=ua, official_code=code).first()
        if city is None:                                # adopt a city seeded by name before the codifier
            city = City.objects.filter(country=ua, official_code="", name=row["name"],
                                       kind__in=["city", "special"] if kind in ("city", "special") else [kind]).first()
        fields = dict(official_code=code, name=row["name"], kind=kind, region=oblast, hromada=hromada,
                      importance=max(importance, city.importance if city else 0), is_active=True,
                      dataset_version=version, timezone="Europe/Kyiv")
        if city is None:
            city = City.objects.create(country=ua, **fields)
            stats["cities_new"] += 1
        else:
            for k, v in fields.items():
                setattr(city, k, v)
            city.save()
            stats["cities_updated"] += 1
        CityAlias.objects.get_or_create(city=city, key=_key(row["name"]),
                                        defaults={"alias": row["name"], "lang": "uk", "source": "katottg"})

    stats["deactivated"] = (City.objects.filter(country=ua, is_active=True).exclude(official_code="")
                            .exclude(official_code__in=seen).update(is_active=False))
    return stats


def _key(s: str) -> str:
    from apps.core.text import norm_key
    return norm_key(s)
