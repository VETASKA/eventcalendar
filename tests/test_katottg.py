from pathlib import Path

from apps.geo.katottg import import_katottg
from apps.geo.models import City, Region
from apps.geo.services import resolve_city

HEADER = "Кодифікатор;;;;;;\nПерший рівень;Другий рівень;Третій рівень;Четвертий рівень;Додатковий рівень;Категорія об'єкта;Назва об'єкта\n"
ROWS = [
    "UA46000000000026241;;;;;O;Львівська",
    "UA46000000000026241;UA46060000000042587;;;;P;Львівський",
    "UA46000000000026241;UA46060000000042587;UA46060250000025047;;;H;Львівська",
    "UA46000000000026241;UA46060000000042587;UA46060250000025047;UA46060250010015970;;M;Львів",
    "UA46000000000026241;UA46060000000042587;UA46060250000025047;UA46060250020072281;;C;Миколаївка",
    "UA80000000000093317;;;;;K;Київ",
    "UA12000000000090473;;;;;O;Дніпропетровська",
    "UA12000000000090473;UA12020000000022633;;;;P;Дніпровський",
    "UA12000000000090473;UA12020000000022633;UA12020010000029810;;;H;Дніпровська",
    "UA12000000000090473;UA12020000000022633;UA12020010000029810;UA12020010040010003;;C;Миколаївка",
]


def write(tmp_path: Path, rows) -> Path:
    p = tmp_path / "k.csv"
    p.write_text(HEADER + "\n".join(rows) + "\n", encoding="utf-8")
    return p


def test_import_adopts_seeded_city_and_keeps_ids(ref, tmp_path):
    seeded_lviv = City.objects.get(name="Львів")
    stats = import_katottg(write(tmp_path, ROWS), "test-1")
    lviv = City.objects.get(name="Львів")
    assert lviv.pk == seeded_lviv.pk and lviv.official_code == "UA46060250010015970"
    assert lviv.region.name == "Львівська" and Region.objects.filter(level="hromada").count() == 2
    assert City.objects.get(name="Київ").kind == "special"
    assert stats["cities_new"] == 2          # two villages
    ids = dict(City.objects.exclude(official_code="").values_list("official_code", "pk"))
    import_katottg(write(tmp_path, ROWS[:-1]), "test-2")    # the second village disappears
    assert dict(City.objects.exclude(official_code="").values_list("official_code", "pk")) == ids
    assert not City.objects.get(official_code="UA12020010040010003").is_active


def test_same_name_villages_are_ambiguous(ref, tmp_path):
    import_katottg(write(tmp_path, ROWS), "t")
    city, problem = resolve_city("UA", "Миколаївка")
    assert city is None and problem == "city_ambiguous"
    assert resolve_city("UA", "Львов")[0].name == "Львів"
