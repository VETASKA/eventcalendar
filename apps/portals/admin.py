from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import Site, SiteDomain


class DomainInline(TabularInline):
    model = SiteDomain
    extra = 0


@admin.register(Site)
class SiteAdmin(ModelAdmin):
    list_display = ("code", "name", "default_locale", "is_default", "is_active")
    filter_horizontal = ("countries",)
    inlines = [DomainInline]
