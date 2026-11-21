from django.contrib import admin

from .models import City, CityAlias, Country, Region


class AliasInline(admin.TabularInline):
    model = CityAlias
    extra = 0
    fields = ("alias", "lang", "source")


@admin.register(City)
class CityAdmin(admin.ModelAdmin):
    list_display = ("name", "region", "kind", "official_code", "importance", "is_active")
    list_filter = ("country", "kind", "is_active")
    search_fields = ("name", "aliases__alias", "official_code")
    raw_id_fields = ("region", "hromada")
    inlines = [AliasInline]


@admin.register(Region)
class RegionAdmin(admin.ModelAdmin):
    list_display = ("name", "level", "official_code", "country")
    list_filter = ("country", "level")
    search_fields = ("name",)


admin.site.register(Country)
