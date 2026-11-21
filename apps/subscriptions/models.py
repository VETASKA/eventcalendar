"""Subscriptions and the delivery journal (spec §7). Sending logic comes in stage 5."""
from django.db import models


class Subscription(models.Model):
    CHANNEL = [("email", "email"), ("telegram", "telegram")]
    STATUS = [("pending", "очікує підтвердження"), ("active", "активна"), ("stopped", "зупинена"),
              ("bounced", "недоставка")]
    site = models.ForeignKey("portals.Site", on_delete=models.CASCADE, related_name="subscriptions")
    channel = models.CharField(max_length=10, choices=CHANNEL)
    address = models.CharField(max_length=320, help_text="email або Telegram ID")
    lang = models.CharField(max_length=5, default="uk")
    filters = models.JSONField(default=dict, help_text='{"city": [..], "topic": [..], "type": [..], "format": [..]}')
    digest = models.BooleanField(default=True)
    status = models.CharField(max_length=10, choices=STATUS, default="pending")
    consent_at = models.DateTimeField(null=True, blank=True)
    consent_source = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "channel", "address"], name="uniq_subscription")]


class Reminder(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="reminders")
    occurrence = models.ForeignKey("catalog.Occurrence", on_delete=models.CASCADE, related_name="reminders")
    send_at = models.DateTimeField(db_index=True)
    status = models.CharField(max_length=10, default="scheduled")   # scheduled | sent | cancelled

    class Meta:
        constraints = [models.UniqueConstraint(fields=["subscription", "occurrence"], name="uniq_reminder")]


class Announcement(models.Model):
    """«New event on this site» — created in the same transaction as the first publication."""
    site = models.ForeignKey("portals.Site", on_delete=models.CASCADE)
    event = models.ForeignKey("catalog.Event", on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    suppressed = models.BooleanField(default=False, help_text="Первинне завантаження — без розсилки")
    digested_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["site", "event"], name="uniq_announcement")]


class Delivery(models.Model):
    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="deliveries")
    kind = models.CharField(max_length=12)   # digest | reminder | change | confirm
    idempotency_key = models.CharField(max_length=120, unique=True)
    status = models.CharField(max_length=10, default="queued")   # queued | sent | failed | unknown
    provider_id = models.CharField(max_length=200, blank=True)
    error = models.TextField(blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
