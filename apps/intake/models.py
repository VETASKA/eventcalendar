"""Where events come from. One IntakeItem per (source, external_id): redelivery never makes a copy."""
import hashlib
import secrets

from django.db import models


class EventSource(models.Model):
    code = models.SlugField(unique=True, help_text="harvey, form, organizer …")
    name = models.CharField(max_length=120)
    token_hash = models.CharField(max_length=64, blank=True, help_text="sha256 токена; сам токен не зберігається")
    is_active = models.BooleanField(default=True)
    trusted = models.BooleanField(default=False, help_text="На майбутнє: автопублікація перевірених джерел")
    last_seen_at = models.DateTimeField(null=True, blank=True)

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
    STATUS = [("queued", "queued"), ("processing", "processing"), ("event_detected", "event_detected"),
              ("not_event", "not_event"), ("needs_review", "needs_review"), ("fetch_error", "fetch_error")]

    source = models.ForeignKey(EventSource, on_delete=models.PROTECT, related_name="items")
    external_id = models.CharField(max_length=200)
    url = models.URLField(max_length=1000, blank=True)
    normalized_url = models.CharField(max_length=1000, blank=True, db_index=True)
    received_at = models.DateTimeField(auto_now_add=True)
    last_received_at = models.DateTimeField(auto_now=True)
    source_updated_at = models.DateTimeField(null=True, blank=True)
    schema_version = models.PositiveSmallIntegerField(default=1)
    payload = models.JSONField(default=dict)
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=STATUS, default="queued", db_index=True)
    reason = models.TextField(blank=True)
    normalized = models.JSONField(default=dict, blank=True)
    event = models.ForeignKey("catalog.Event", null=True, blank=True, on_delete=models.SET_NULL,
                              related_name="intake_items")
    initial_load = models.BooleanField(default=False, help_text="Первинне завантаження: без розсилки")
    removed_in_source = models.BooleanField(default=False)
    attempts = models.PositiveIntegerField(default=0)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["source", "external_id"], name="uniq_source_external")]

    def __str__(self):
        return f"{self.source.code}:{self.external_id}"
