from django.contrib import admin

from .models import Site, SiteDomain


class DomainInline(admin.TabularInline):
    model = SiteDomain
    extra = 0


@admin.register(Site)
class SiteAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "default_locale", "is_default", "is_active")
    filter_horizontal = ("countries",)
    inlines = [DomainInline]
