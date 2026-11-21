"""Geography: countries, regions, cities and their aliases. Internal IDs never change on re-import."""
from django.db import models

from apps.core.text import norm_key


class Country(models.Model):
    code = models.CharField(max_length=2, primary_key=True, help_text="ISO 3166-1 alpha-2")
    names = models.JSONField(default=dict, help_text='{"uk": "Україна", "en": "Ukraine", "pl": "Ukraina"}')
    timezone = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name_plural = "countries"

    def __str__(self):
        return self.names.get("uk") or self.code


class Region(models.Model):
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="regions")
    official_code = models.CharField(max_length=32, blank=True, db_index=True)
    name = models.CharField(max_length=200, help_text="Офіційна назва (українською для UA)")
    names = models.JSONField(default=dict, blank=True)
    level = models.CharField(max_length=16, default="oblast")   # oblast | raion | hromada
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="children")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["country", "official_code"], name="uniq_region_code",
                                               condition=~models.Q(official_code=""))]

    def __str__(self):
        return self.name


class City(models.Model):
    KIND = [("city", "місто"), ("special", "місто зі спецстатусом"), ("town", "селище"), ("village", "село"),
            ("district", "район у місті"), ("other", "інше")]
    country = models.ForeignKey(Country, on_delete=models.PROTECT, related_name="cities")
    region = models.ForeignKey(Region, null=True, blank=True, on_delete=models.PROTECT, related_name="cities")
    hromada = models.ForeignKey(Region, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    official_code = models.CharField(max_length=32, blank=True, db_index=True)
    kind = models.CharField(max_length=10, choices=KIND, default="city")
    name = models.CharField(max_length=200, help_text="Офіційне написання")
    names = models.JSONField(default=dict, blank=True, help_text='{"en": "Kyiv", "pl": "Kijów"}')
    timezone = models.CharField(max_length=64, blank=True)
    is_active = models.BooleanField(default=True, help_text="Знято з довідника, але старі зв'язки збережено")
    dataset_version = models.CharField(max_length=40, blank=True)
    importance = models.PositiveSmallIntegerField(default=0, help_text="Вище — першим у пошуку")

    class Meta:
        verbose_name_plural = "cities"
        constraints = [models.UniqueConstraint(fields=["country", "official_code"], name="uniq_city_code",
                                               condition=~models.Q(official_code=""))]
        indexes = [models.Index(fields=["country", "name"])]

    def __str__(self):
        return f"{self.name} ({self.region})" if self.region_id else self.name

    def label(self, lang: str = "uk") -> str:
        return self.names.get(lang) or self.name


class CityAlias(models.Model):
    city = models.ForeignKey(City, on_delete=models.CASCADE, related_name="aliases")
    alias = models.CharField(max_length=200)
    key = models.CharField(max_length=200, db_index=True, editable=False)
    lang = models.CharField(max_length=5, blank=True)
    source = models.CharField(max_length=40, blank=True, help_text="katottg | harvey | manual …")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["city", "key"], name="uniq_city_alias")]

    def save(self, *a, **kw):
        self.key = norm_key(self.alias)
        super().save(*a, **kw)

    def __str__(self):
        return self.alias
