"""The shared catalogue: events, their sessions, classification, per-site publication and revisions."""
from django.conf import settings
from django.db import models
from django.utils.text import slugify

LANGS = [("uk", "uk"), ("en", "en"), ("pl", "pl"), ("ru", "ru"), ("other", "other")]


class Topic(models.Model):
    code = models.SlugField(unique=True)
    names = models.JSONField(default=dict, help_text='{"uk": "Культура", "en": "Culture", "pl": "Kultura"}')
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "code"]

    def __str__(self):
        return self.names.get("uk") or self.code


class EventType(models.Model):
    code = models.SlugField(unique=True)
    names = models.JSONField(default=dict, help_text='{"uk": "Стендап", "en": "Stand-up", "pl": "Stand-up"}')
    position = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["position", "code"]

    def __str__(self):
        return self.names.get("uk") or self.code


class Event(models.Model):
    """The shared card. Fields here are the CURRENT APPROVED version once published; before the first
    approval they are the working draft. Later changes from import / organizers go to EventRevision."""

    FORMAT = [("offline", "офлайн"), ("online", "онлайн"), ("hybrid", "гібрид")]
    STATE = [("draft", "чернетка"), ("pending", "на модерації"), ("approved", "схвалено"),
             ("rejected", "відхилено"), ("withdrawn", "знято")]

    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True, help_text="Короткий анонс своїми словами")
    original_language = models.CharField(max_length=8, choices=LANGS, blank=True)
    format = models.CharField(max_length=8, choices=FORMAT, blank=True)
    event_type = models.ForeignKey(EventType, null=True, blank=True, on_delete=models.PROTECT)
    topics = models.ManyToManyField(Topic, blank=True)
    country = models.ForeignKey("geo.Country", null=True, blank=True, on_delete=models.PROTECT)
    organizer_name = models.CharField(max_length=300, blank=True)
    organizer_site = models.URLField(max_length=500, blank=True)
    organization = models.ForeignKey("organizers.Organization", null=True, blank=True,
                                     on_delete=models.SET_NULL, related_name="events")
    source_url = models.URLField(max_length=1000, blank=True, help_text="Першоджерело")
    registration_url = models.URLField(max_length=1000, blank=True, help_text="Реєстрація / квитки")
    price_text = models.CharField(max_length=120, blank=True)
    # why this event belongs to a country's storefront (spec §4): {"ua_phone": true, "lang_uk": true, ...}
    geo_signals = models.JSONField(default=dict, blank=True)
    geo_reason = models.CharField(max_length=300, blank=True, help_text="Підстава ручного уточнення географії")

    state = models.CharField(max_length=10, choices=STATE, default="draft", db_index=True)
    review_flags = models.JSONField(default=list, blank=True, help_text="Що перевірити модератору")
    manual_fields = models.JSONField(default=list, blank=True,
                                     help_text="Поля, змінені вручну: імпорт їх не перезаписує")
    revision = models.PositiveIntegerField(default=1, help_text="Номер для перевірки одночасного редагування")
    organizer_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["state", "country"])]

    def __str__(self):
        return self.title

    @property
    def slug(self) -> str:
        return slugify(self.title, allow_unicode=True)[:80] or "event"


class EventTranslation(models.Model):
    """Optional editorial translation of the title / summary (spec §3: shown when present)."""
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="translations")
    lang = models.CharField(max_length=5)
    title = models.CharField(max_length=300)
    summary = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "lang"], name="uniq_event_translation")]


class Occurrence(models.Model):
    """One session. start_date / end_date are LOCAL dates and are always filled: the calendar range
    query works on them. starts_at / ends_at (UTC) only when the time is known."""

    PRECISION = [("datetime", "точний час"), ("all_day", "весь день"), ("date", "час уточнюється")]
    STATUS = [("scheduled", "заплановано"), ("postponed", "перенесено без дати"),
              ("rescheduled", "перенесено"), ("cancelled", "скасовано")]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="occurrences")
    start_date = models.DateField()
    end_date = models.DateField()
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    timezone = models.CharField(max_length=64, default="Europe/Kyiv")
    precision = models.CharField(max_length=8, choices=PRECISION, default="date")
    status = models.CharField(max_length=12, choices=STATUS, default="scheduled")
    city = models.ForeignKey("geo.City", null=True, blank=True, on_delete=models.PROTECT)
    venue = models.CharField(max_length=300, blank=True)
    address = models.CharField(max_length=500, blank=True)
    source_key = models.CharField(max_length=200, blank=True,
                                  help_text="Ключ сеансу з джерела, щоб повторний імпорт не дублював")

    class Meta:
        ordering = ["start_date", "starts_at", "id"]
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

    STATUS = [("pending", "очікує"), ("published", "опубліковано"), ("rejected", "відхилено"),
              ("unpublished", "знято з публікації")]

    site = models.ForeignKey("portals.Site", on_delete=models.CASCADE, related_name="publications")
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="publications")
    status = models.CharField(max_length=12, choices=STATUS, default="pending", db_index=True)
    first_published_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    reason = models.CharField(max_length=500, blank=True)
    # a moderator removed it: a re-import must never bring it back by itself
    blocked = models.BooleanField(default=False)
    featured_from = models.DateField(null=True, blank=True)
    featured_to = models.DateField(null=True, blank=True)
    canonical_url = models.URLField(max_length=500, blank=True, help_text="Основний URL, якщо картка на кількох доменах")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "event"], name="uniq_site_event")]
        indexes = [models.Index(fields=["site", "status"])]


class EventRevision(models.Model):
    """A proposed or applied version of the card: from a re-import, an organizer or a moderator."""

    ORIGIN = [("import", "імпорт"), ("organizer", "організатор"), ("moderator", "модератор")]
    STATUS = [("proposed", "запропоновано"), ("approved", "застосовано"), ("rejected", "відхилено"),
              ("superseded", "замінено новішою")]

    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="revisions")
    base_revision = models.PositiveIntegerField(help_text="Event.revision, на якій зроблено зміну")
    origin = models.CharField(max_length=10, choices=ORIGIN)
    status = models.CharField(max_length=10, choices=STATUS, default="proposed", db_index=True)
    priority = models.BooleanField(default=False, help_text="Перенос / скасування — нагору черги")
    changes = models.JSONField(default=dict, help_text="Тільки змінені поля: {field: new_value}")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    source_item = models.ForeignKey("intake.IntakeItem", null=True, blank=True, on_delete=models.SET_NULL)
    created_at = models.DateTimeField(auto_now_add=True)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-priority", "created_at"]
