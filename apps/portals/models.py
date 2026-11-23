"""A Site is one public storefront (domain, brand, locales, geography) over the shared catalogue."""
from django.db import models


class Site(models.Model):
    code = models.SlugField("код", unique=True, help_text="Короткий код: ua, pl-test …")
    name = models.CharField("название", max_length=120)
    names = models.JSONField("название на языках сайта", default=dict, blank=True,
                             help_text='{"en": "EventCalendar Ukraine", "pl": "EventCalendar Ukraina"}')
    default_locale = models.CharField("язык по умолчанию", max_length=5, default="uk")
    locales = models.JSONField("языки сайта", default=list, help_text='Напр. ["uk", "en", "pl"]')
    timezone = models.CharField("часовой пояс", max_length=64, default="Europe/Kyiv")
    countries = models.ManyToManyField("geo.Country", verbose_name="страны", blank=True, related_name="sites")
    # online events with no city: shown here only after a moderator ties them to this storefront
    show_online = models.BooleanField("показывать онлайн-события", default=True)
    theme = models.CharField("оформление", max_length=40, default="default")
    digest_weekday = models.PositiveSmallIntegerField("день дайджеста", default=1, help_text="0 = понедельник. Сейчас расписание общее: вторник 11:00 по Киеву")
    digest_time = models.TimeField("время дайджеста", default="11:00")
    # names of environment variables / secret entries, never the secrets themselves
    secrets_ref = models.JSONField("ссылки на секреты", default=dict, blank=True,
                                   help_text='Имена переменных окружения, не сами секреты: '
                                             '{"telegram_token": "UA_TG_TOKEN"}')
    is_active = models.BooleanField("включён", default=True)
    is_default = models.BooleanField("сайт по умолчанию", default=False,
                                     help_text="Для запросов с неизвестного домена (локально)")

    class Meta:
        verbose_name = "сайт"
        verbose_name_plural = "сайты"

    def __str__(self):
        return self.name

    def country_codes(self) -> set[str]:
        return set(self.countries.values_list("code", flat=True))


class SiteDomain(models.Model):
    site = models.ForeignKey(Site, verbose_name="сайт", on_delete=models.CASCADE, related_name="domains")
    host = models.CharField("домен", max_length=253, unique=True)
    is_primary = models.BooleanField("основной", default=False)

    class Meta:
        verbose_name = "домен"
        verbose_name_plural = "домены"

    def save(self, *a, **kw):
        self.host = self.host.strip().lower().rstrip(".")
        super().save(*a, **kw)

    def __str__(self):
        return self.host
