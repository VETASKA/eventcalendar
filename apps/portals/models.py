"""A Site is one public storefront (domain, brand, locales, geography) over the shared catalogue."""
from django.db import models


class Site(models.Model):
    code = models.SlugField(unique=True, help_text="Короткий код: ua, pl-test …")
    name = models.CharField(max_length=120)
    default_locale = models.CharField(max_length=5, default="uk")
    locales = models.JSONField(default=list, help_text='Напр. ["uk", "en", "pl"]')
    timezone = models.CharField(max_length=64, default="Europe/Kyiv")
    countries = models.ManyToManyField("geo.Country", blank=True, related_name="sites")
    # online events with no city: shown here only after a moderator ties them to this storefront
    show_online = models.BooleanField(default=True)
    theme = models.CharField(max_length=40, default="default")
    digest_weekday = models.PositiveSmallIntegerField(default=4, help_text="0 = понеділок")
    digest_time = models.TimeField(default="10:00")
    # names of environment variables / secret entries, never the secrets themselves
    secrets_ref = models.JSONField(default=dict, blank=True,
                                   help_text='{"telegram_token": "UA_TG_TOKEN", "mail_from": "UA_MAIL_FROM"}')
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False, help_text="Сайт для запитів без відомого домену (локально)")

    def __str__(self):
        return self.name

    def country_codes(self) -> set[str]:
        return set(self.countries.values_list("code", flat=True))


class SiteDomain(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name="domains")
    host = models.CharField(max_length=253, unique=True)
    is_primary = models.BooleanField(default=False)

    def save(self, *a, **kw):
        self.host = self.host.strip().lower().rstrip(".")
        super().save(*a, **kw)

    def __str__(self):
        return self.host
