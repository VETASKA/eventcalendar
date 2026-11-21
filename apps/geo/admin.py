from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import City, CityAlias, Country, Region


class AliasInline(TabularInline):
    model = CityAlias
    extra = 1
    fields = ("alias", "lang", "source")


@admin.register(City)
class CityAdmin(ModelAdmin):
    list_display = ("name", "region", "kind", "importance", "is_active")
    list_filter = ("country", "kind", "is_active")
    search_fields = ("name", "aliases__alias", "official_code")
    raw_id_fields = ("region", "hromada")
    inlines = [AliasInline]


@admin.register(Region)
class RegionAdmin(ModelAdmin):
    list_display = ("name", "level", "official_code", "country")
    list_filter = ("country", "level")
    search_fields = ("name",)


@admin.register(Country)
class CountryAdmin(ModelAdmin):
    list_display = ("code", "__str__", "timezone")
