"""Subscriptions and the delivery journal (spec §7). Sending logic comes in stage 5."""
from django.db import models


class Subscription(models.Model):
    CHANNEL = [("email", "email"), ("telegram", "Telegram")]
    STATUS = [("pending", "ждёт подтверждения"), ("active", "активна"), ("stopped", "остановлена"),
              ("bounced", "недоставка")]
    site = models.ForeignKey("portals.Site", verbose_name="сайт", on_delete=models.CASCADE,
                             related_name="subscriptions")
    channel = models.CharField("канал", max_length=10, choices=CHANNEL)
    address = models.CharField("адрес", max_length=320, help_text="email или Telegram ID")
    lang = models.CharField("язык", max_length=5, default="uk")
    filters = models.JSONField("интересы", default=dict,
                               help_text='{"city": [..], "topic": [..], "type": [..], "format": [..]}')
    digest = models.BooleanField("еженедельный дайджест", default=True)
    status = models.CharField("статус", max_length=10, choices=STATUS, default="pending")
    consent_at = models.DateTimeField("согласие получено", null=True, blank=True)
    consent_source = models.CharField("откуда согласие", max_length=200, blank=True)
    created_at = models.DateTimeField("создана", auto_now_add=True)

    class Meta:
        verbose_name = "подписка"
        verbose_name_plural = "подписки"
        constraints = [models.UniqueConstraint(fields=["site", "channel", "address"], name="uniq_subscription")]


class Reminder(models.Model):
    STATUS = [("scheduled", "запланировано"), ("sent", "отправлено"), ("cancelled", "отменено")]
    subscription = models.ForeignKey(Subscription, verbose_name="подписка", on_delete=models.CASCADE,
                                     related_name="reminders")
    occurrence = models.ForeignKey("catalog.Occurrence", verbose_name="сеанс", on_delete=models.CASCADE,
                                   related_name="reminders")
    send_at = models.DateTimeField("отправить", db_index=True)
    status = models.CharField("статус", max_length=10, choices=STATUS, default="scheduled")

    class Meta:
        verbose_name = "напоминание"
        verbose_name_plural = "напоминания"
        constraints = [models.UniqueConstraint(fields=["subscription", "occurrence"], name="uniq_reminder")]


class Announcement(models.Model):
    """«New event on this site» — created in the same transaction as the first publication."""
    site = models.ForeignKey("portals.Site", verbose_name="сайт", on_delete=models.CASCADE)
    event = models.ForeignKey("catalog.Event", verbose_name="событие", on_delete=models.CASCADE)
    created_at = models.DateTimeField("создан", auto_now_add=True)
    suppressed = models.BooleanField("без рассылки", default=False, help_text="Первая выгрузка или прошедшее событие")
    digested_at = models.DateTimeField("попал в дайджест", null=True, blank=True)

    class Meta:
        verbose_name = "анонс нового события"
        verbose_name_plural = "анонсы новых событий"
        constraints = [models.UniqueConstraint(fields=["site", "event"], name="uniq_announcement")]


class Delivery(models.Model):
    KIND = [("digest", "дайджест"), ("reminder", "напоминание"), ("change", "изменение"), ("confirm", "подтверждение")]
    STATUS = [("queued", "в очереди"), ("sent", "отправлено"), ("failed", "ошибка"), ("unknown", "неясно")]
    subscription = models.ForeignKey(Subscription, verbose_name="подписка", on_delete=models.CASCADE,
                                     related_name="deliveries")
    kind = models.CharField("что", max_length=12, choices=KIND)
    idempotency_key = models.CharField(max_length=120, unique=True)
    status = models.CharField("статус", max_length=10, choices=STATUS, default="queued")
    provider_id = models.CharField("ID у провайдера", max_length=200, blank=True)
    error = models.TextField("ошибка", blank=True)
    attempts = models.PositiveSmallIntegerField("попыток", default=0)
    created_at = models.DateTimeField("создано", auto_now_add=True)
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)

    class Meta:
        verbose_name = "отправка"
        verbose_name_plural = "журнал отправок"
