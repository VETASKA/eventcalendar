"""Where events come from. One IntakeItem per (source, external_id): redelivery never makes a copy."""
import hashlib
import secrets

from django.db import models


class EventSource(models.Model):
    code = models.SlugField("код", unique=True, help_text="harvey, form, organizer …")
    name = models.CharField("название", max_length=120)
    token_hash = models.CharField(max_length=64, blank=True, help_text="sha256 токена; сам токен не хранится")
    is_active = models.BooleanField("включён", default=True)
    trusted = models.BooleanField("проверенный", default=False,
                                  help_text="На будущее: автопубликация из проверенных источников")
    last_seen_at = models.DateTimeField("последний приём", null=True, blank=True)

    class Meta:
        verbose_name = "источник"
        verbose_name_plural = "источники"

    def __str__(self):
        return self.name

    @staticmethod
    def hash_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def issue_token(self) -> str:
        token = "ec_" + secrets.token_urlsafe(32)
        self.token_hash = self.hash_token(token)
        self.save(update_fields=["token_hash"])
        return token


class IntakeItem(models.Model):
    # codes are the spec's (§5.3); labels are for the admin
    STATUS = [("queued", "в очереди"), ("processing", "обрабатывается"), ("event_detected", "событие"),
              ("not_event", "не событие"), ("needs_review", "нужна проверка"), ("fetch_error", "ошибка загрузки")]

    source = models.ForeignKey(EventSource, verbose_name="источник", on_delete=models.PROTECT, related_name="items")
    external_id = models.CharField("ID в источнике", max_length=200)
    url = models.URLField("адрес", max_length=1000, blank=True)
    normalized_url = models.CharField("адрес (нормализованный)", max_length=1000, blank=True, db_index=True)
    received_at = models.DateTimeField("впервые получено", auto_now_add=True)
    last_received_at = models.DateTimeField("последний раз получено", auto_now=True)
    source_updated_at = models.DateTimeField("изменено в источнике", null=True, blank=True)
    schema_version = models.PositiveSmallIntegerField("версия схемы", default=1)
    payload = models.JSONField("как пришло", default=dict)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField("результат разбора", max_length=16, choices=STATUS, default="queued", db_index=True)
    reason = models.TextField("причина", blank=True)
    normalized = models.JSONField("после разбора", default=dict, blank=True)
    event = models.ForeignKey("catalog.Event", verbose_name="событие", null=True, blank=True,
                              on_delete=models.SET_NULL, related_name="intake_items")
    initial_load = models.BooleanField("первая выгрузка", default=False, help_text="Без рассылки о новом событии")
    removed_in_source = models.BooleanField("удалено в источнике", default=False)
    attempts = models.PositiveIntegerField("попыток", default=0)
    processed_at = models.DateTimeField("обработано", null=True, blank=True)

    class Meta:
        verbose_name = "запись импорта"
        verbose_name_plural = "записи импорта"
        constraints = [models.UniqueConstraint(fields=["source", "external_id"], name="uniq_source_external")]

    def __str__(self):
        return f"{self.source.code}:{self.external_id}"
