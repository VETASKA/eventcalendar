"""Geography: countries, regions, cities and their aliases. Internal IDs never change on re-import."""
from django.db import models

from apps.core.text import norm_key


class Country(models.Model):
    code = models.CharField("код", max_length=2, primary_key=True, help_text="ISO 3166-1 alpha-2, напр. UA")
    names = models.JSONField("названия", default=dict, help_text='{"uk": "Україна", "en": "Ukraine", "pl": "Ukraina"}')
    timezone = models.CharField("часовой пояс", max_length=64, blank=True)

    class Meta:
        verbose_name = "страна"
        verbose_name_plural = "страны"

    def __str__(self):
        return self.names.get("uk") or self.code


class Region(models.Model):
    LEVEL = [("oblast", "область"), ("raion", "район"), ("hromada", "громада")]
    country = models.ForeignKey(Country, verbose_name="страна", on_delete=models.PROTECT, related_name="regions")
    official_code = models.CharField("официальный код", max_length=32, blank=True, db_index=True)
    name = models.CharField("название", max_length=200, help_text="Официальное название (для UA — по-украински)")
    names = models.JSONField("переводы названия", default=dict, blank=True)
    level = models.CharField("уровень", max_length=16, choices=LEVEL, default="oblast")
    parent = models.ForeignKey("self", verbose_name="входит в", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="children")

    class Meta:
        verbose_name = "регион"
        verbose_name_plural = "регионы"
        constraints = [models.UniqueConstraint(fields=["country", "official_code"], name="uniq_region_code",
                                               condition=~models.Q(official_code=""))]

    def __str__(self):
        return self.name


class City(models.Model):
    KIND = [("city", "город"), ("special", "город со спецстатусом"), ("town", "посёлок"), ("village", "село"),
            ("district", "район города"), ("other", "другое")]
    country = models.ForeignKey(Country, verbose_name="страна", on_delete=models.PROTECT, related_name="cities")
    region = models.ForeignKey(Region, verbose_name="область", null=True, blank=True, on_delete=models.PROTECT,
                               related_name="cities")
    hromada = models.ForeignKey(Region, verbose_name="громада", null=True, blank=True, on_delete=models.PROTECT,
                                related_name="+")
    official_code = models.CharField("официальный код", max_length=32, blank=True, db_index=True)
    kind = models.CharField("тип", max_length=10, choices=KIND, default="city")
    name = models.CharField("название", max_length=200, help_text="Официальное написание (для UA — по-украински)")
    names = models.JSONField("переводы названия", default=dict, blank=True, help_text='{"en": "Kyiv", "pl": "Kijów"}')
    timezone = models.CharField("часовой пояс", max_length=64, blank=True)
    is_active = models.BooleanField("действует", default=True,
                                    help_text="Снят со справочника, но старые связи сохранены")
    dataset_version = models.CharField("версия справочника", max_length=40, blank=True)
    importance = models.PositiveSmallIntegerField("вес", default=0,
                                                  help_text="Чем выше, тем раньше в поиске и при одинаковых названиях")

    class Meta:
        verbose_name = "город"
        verbose_name_plural = "города"
        constraints = [models.UniqueConstraint(fields=["country", "official_code"], name="uniq_city_code",
                                               condition=~models.Q(official_code=""))]
        indexes = [models.Index(fields=["country", "name"])]

    def __str__(self):
        return f"{self.name} ({self.region})" if self.region_id else self.name

    def label(self, lang: str = "uk") -> str:
        return self.names.get(lang) or self.name


class CityAlias(models.Model):
    city = models.ForeignKey(City, verbose_name="город", on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField("вариант написания", max_length=200)
    key = models.CharField(max_length=200, db_index=True, editable=False)
    lang = models.CharField("язык", max_length=5, blank=True)
    source = models.CharField("откуда", max_length=40, blank=True, help_text="katottg | harvey | seed | manual")

    class Meta:
        verbose_name = "вариант названия"
        verbose_name_plural = "варианты названия"
        constraints = [models.UniqueConstraint(fields=["city", "key"], name="uniq_city_alias")]

    def save(self, *a, **kw):
        self.key = norm_key(self.alias)
        super().save(*a, **kw)

    def __str__(self):
        return self.alias
