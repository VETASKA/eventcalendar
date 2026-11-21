"""The shared catalogue: events, their sessions, classification, per-site publication and revisions."""
from django.conf import settings
from django.db import models
from django.utils.text import slugify

LANGS = [("uk", "украинский"), ("en", "английский"), ("pl", "польский"), ("ru", "русский"), ("other", "другой")]


class Topic(models.Model):
    code = models.SlugField("код", unique=True)
    names = models.JSONField("названия", default=dict, help_text='{"uk": "Культура", "en": "Culture", "pl": "Kultura"}')
    position = models.PositiveSmallIntegerField("порядок", default=0)
    is_active = models.BooleanField("включена", default=True)

    class Meta:
        ordering = ["position", "code"]
        verbose_name = "тематика"
        verbose_name_plural = "тематики"

    def __str__(self):
        return self.names.get("uk") or self.code


class EventType(models.Model):
    code = models.SlugField("код", unique=True)
    names = models.JSONField("названия", default=dict, help_text='{"uk": "Стендап", "en": "Stand-up", "pl": "Stand-up"}')
    position = models.PositiveSmallIntegerField("порядок", default=0)
    is_active = models.BooleanField("включён", default=True)

    class Meta:
        ordering = ["position", "code"]
        verbose_name = "тип события"
        verbose_name_plural = "типы событий"

    def __str__(self):
        return self.names.get("uk") or self.code


class Event(models.Model):
    """The shared card. Fields here are the CURRENT APPROVED version once published; before the first
    approval they are the working draft. Later changes from import / organizers go to EventRevision."""

    FORMAT = [("offline", "офлайн"), ("online", "онлайн"), ("hybrid", "гибрид")]
    STATE = [("draft", "черновик"), ("pending", "на модерации"), ("approved", "одобрено"),
             ("rejected", "отклонено"), ("withdrawn", "снято источником")]

    title = models.CharField("название", max_length=300)
    summary = models.TextField("краткий анонс", blank=True, help_text="Своими словами, 1–3 предложения")
    original_language = models.CharField("язык анонса", max_length=8, choices=LANGS, blank=True)
    format = models.CharField("формат", max_length=8, choices=FORMAT, blank=True)
    event_type = models.ForeignKey(EventType, verbose_name="тип", null=True, blank=True, on_delete=models.PROTECT)
    topics = models.ManyToManyField(Topic, verbose_name="тематики", blank=True)
    country = models.ForeignKey("geo.Country", verbose_name="страна", null=True, blank=True, on_delete=models.PROTECT)
    organizer_name = models.CharField("организатор", max_length=300, blank=True)
    organizer_site = models.URLField("сайт организатора", max_length=500, blank=True)
    organization = models.ForeignKey("organizers.Organization", verbose_name="организация (кабинет)", null=True,
                                     blank=True, on_delete=models.SET_NULL, related_name="events")
    source_url = models.URLField("первоисточник", max_length=1000, blank=True)
    registration_url = models.URLField("регистрация / билеты", max_length=1000, blank=True)
    price_text = models.CharField("цена", max_length=120, blank=True)
    # why this event belongs to a country's storefront (spec §4): {"ua_phone": true, "lang_uk": true, ...}
    geo_signals = models.JSONField("признаки географии", default=dict, blank=True)
    geo_reason = models.CharField("основание географии", max_length=300, blank=True,
                                  help_text="Почему событие отнесено к стране, если уточняли вручную")

    state = models.CharField("статус", max_length=10, choices=STATE, default="draft", db_index=True)
    review_flags = models.JSONField("что проверить", default=list, blank=True)
    manual_fields = models.JSONField("поля, изменённые вручную", default=list, blank=True,
                                     help_text="Импорт их не перезаписывает")
    revision = models.PositiveIntegerField("версия", default=1)
    organizer_verified = models.BooleanField("организатор подтверждён", default=False)
    created_at = models.DateTimeField("добавлено", auto_now_add=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        verbose_name = "событие"
        verbose_name_plural = "события"
        indexes = [models.Index(fields=["state", "country"])]

    def __str__(self):
        return self.title

    @property
    def slug(self) -> str:
        return slugify(self.title, allow_unicode=True)[:80] or "event"


class EventTranslation(models.Model):
    """Optional editorial translation of the title / summary (spec §3: shown when present)."""
    event = models.ForeignKey(Event, verbose_name="событие", on_delete=models.CASCADE, related_name="translations")
    lang = models.CharField("язык", max_length=5, choices=[("uk", "uk"), ("en", "en"), ("pl", "pl")])
    title = models.CharField("название", max_length=300)
    summary = models.TextField("анонс", blank=True)

    class Meta:
        verbose_name = "перевод"
        verbose_name_plural = "переводы"
        constraints = [models.UniqueConstraint(fields=["event", "lang"], name="uniq_event_translation")]


class Occurrence(models.Model):
    """One session. start_date / end_date are LOCAL dates and are always filled: the calendar range
    query works on them. starts_at / ends_at (UTC) only when the time is known."""

    PRECISION = [("datetime", "точное время"), ("all_day", "весь день"), ("date", "время уточняется")]
    STATUS = [("scheduled", "по плану"), ("postponed", "перенесено без даты"),
              ("rescheduled", "перенесено"), ("cancelled", "отменено")]

    event = models.ForeignKey(Event, verbose_name="событие", on_delete=models.CASCADE, related_name="occurrences")
    start_date = models.DateField("с")
    end_date = models.DateField("по")
    starts_at = models.DateTimeField("начало", null=True, blank=True)
    ends_at = models.DateTimeField("окончание", null=True, blank=True)
    timezone = models.CharField("часовой пояс", max_length=64, default="Europe/Kyiv")
    precision = models.CharField("время", max_length=8, choices=PRECISION, default="date")
    status = models.CharField("статус", max_length=12, choices=STATUS, default="scheduled")
    city = models.ForeignKey("geo.City", verbose_name="город", null=True, blank=True, on_delete=models.PROTECT)
    venue = models.CharField("площадка", max_length=300, blank=True)
    address = models.CharField("адрес", max_length=500, blank=True)
    source_key = models.CharField("ключ источника", max_length=200, blank=True,
                                  help_text="Чтобы повторный импорт не дублировал сеанс")

    class Meta:
        ordering = ["start_date", "starts_at", "id"]
        verbose_name = "сеанс"
        verbose_name_plural = "сеансы"
        indexes = [models.Index(fields=["start_date", "end_date"]), models.Index(fields=["city", "start_date"])]
        constraints = [
            models.CheckConstraint(condition=models.Q(end_date__gte=models.F("start_date")), name="occ_dates_order"),
            models.UniqueConstraint(fields=["event", "source_key"], name="uniq_occ_source_key",
                                    condition=~models.Q(source_key="")),
        ]

    def __str__(self):
        return f"{self.event} — {self.start_date}"


class SitePublication(models.Model):
    """Whether an event is visible on one storefront. Each site's editors decide for themselves."""

    STATUS = [("pending", "ждёт решения"), ("published", "опубликовано"), ("rejected", "отклонено"),
              ("unpublished", "снято с публикации")]

    site = models.ForeignKey("portals.Site", verbose_name="сайт", on_delete=models.CASCADE,
                             related_name="publications")
    event = models.ForeignKey(Event, verbose_name="событие", on_delete=models.CASCADE, related_name="publications")
    status = models.CharField("статус", max_length=12, choices=STATUS, default="pending", db_index=True)
    first_published_at = models.DateTimeField("впервые опубликовано", null=True, blank=True)
    published_at = models.DateTimeField("опубликовано", null=True, blank=True)
    reason = models.CharField("причина", max_length=500, blank=True)
    # a moderator removed it: a re-import must never bring it back by itself
    blocked = models.BooleanField("не возвращать при импорте", default=False)
    featured_from = models.DateField("рекомендовано с", null=True, blank=True)
    featured_to = models.DateField("рекомендовано по", null=True, blank=True)
    canonical_url = models.URLField("основной URL", max_length=500, blank=True,
                                    help_text="Если карточка одинаковая на нескольких доменах")

    class Meta:
        verbose_name = "публикация"
        verbose_name_plural = "публикации"
        constraints = [models.UniqueConstraint(fields=["site", "event"], name="uniq_site_event")]
        indexes = [models.Index(fields=["site", "status"])]

    def __str__(self):
        return f"{self.event} @ {self.site}"


class EventRevision(models.Model):
    """A proposed or applied version of the card: from a re-import, an organizer or a moderator."""

    ORIGIN = [("import", "импорт"), ("organizer", "организатор"), ("moderator", "модератор")]
    STATUS = [("proposed", "предложено"), ("approved", "применено"), ("rejected", "отклонено"),
              ("superseded", "заменено новым")]

    event = models.ForeignKey(Event, verbose_name="событие", on_delete=models.CASCADE, related_name="revisions")
    base_revision = models.PositiveIntegerField("к версии")
    origin = models.CharField("откуда", max_length=10, choices=ORIGIN)
    status = models.CharField("статус", max_length=10, choices=STATUS, default="proposed", db_index=True)
    priority = models.BooleanField("срочно", default=False, help_text="Перенос / отмена — наверх очереди")
    changes = models.JSONField("изменения", default=dict)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="автор", null=True, blank=True,
                               on_delete=models.SET_NULL)
    source_item = models.ForeignKey("intake.IntakeItem", verbose_name="запись импорта", null=True, blank=True,
                                    on_delete=models.SET_NULL)
    created_at = models.DateTimeField("создано", auto_now_add=True)
    decided_at = models.DateTimeField("решено", null=True, blank=True)

    class Meta:
        ordering = ["-priority", "created_at"]
        verbose_name = "предложенное изменение"
        verbose_name_plural = "предложенные изменения"

    def __str__(self):
        return f"{self.get_origin_display()}: {self.event}"
