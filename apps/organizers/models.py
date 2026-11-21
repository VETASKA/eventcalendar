"""Organizers and their rights on events (spec §6). Logic comes in stage 4; the tables exist now."""
from django.conf import settings
from django.db import models


class Organization(models.Model):
    name = models.CharField("название", max_length=300)
    website = models.URLField("сайт", max_length=500, blank=True)
    official_host = models.CharField("подтверждённый хост", max_length=253, blank=True)
    created_at = models.DateTimeField("создано", auto_now_add=True)

    class Meta:
        verbose_name = "организация"
        verbose_name_plural = "организации"

    def __str__(self):
        return self.name


class Membership(models.Model):
    ROLE = [("owner", "владелец"), ("member", "участник")]
    organization = models.ForeignKey(Organization, verbose_name="организация", on_delete=models.CASCADE,
                                     related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", on_delete=models.CASCADE)
    role = models.CharField("роль", max_length=10, choices=ROLE, default="member")

    class Meta:
        verbose_name = "участник организации"
        verbose_name_plural = "участники организаций"
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="uniq_membership")]


class Claim(models.Model):
    METHOD = [("file", "файл на сайте"), ("email", "корпоративная почта"), ("manual", "ручная проверка")]
    STATUS = [("open", "открыт"), ("verified", "контроль подтверждён"), ("approved", "права выданы"),
              ("rejected", "отклонён"), ("expired", "просрочен")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", on_delete=models.CASCADE)
    event = models.ForeignKey("catalog.Event", verbose_name="событие", on_delete=models.CASCADE,
                              related_name="claims")
    organization = models.ForeignKey(Organization, verbose_name="организация", null=True, blank=True,
                                     on_delete=models.SET_NULL)
    method = models.CharField("способ", max_length=8, choices=METHOD)
    host = models.CharField("хост", max_length=253, blank=True)
    verify_path = models.CharField("путь к файлу", max_length=500, blank=True)
    token_hash = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField("действует до", null=True, blank=True)
    attempts = models.PositiveSmallIntegerField("попыток", default=0)
    status = models.CharField("статус", max_length=10, choices=STATUS, default="open")
    evidence = models.TextField("доказательства", blank=True)
    decision_note = models.TextField("решение модератора", blank=True)
    created_at = models.DateTimeField("создан", auto_now_add=True)

    class Meta:
        verbose_name = "запрос «Это моё событие»"
        verbose_name_plural = "запросы «Это моё событие»"


class EventGrant(models.Model):
    event = models.ForeignKey("catalog.Event", verbose_name="событие", on_delete=models.CASCADE,
                              related_name="grants")
    organization = models.ForeignKey(Organization, verbose_name="организация", on_delete=models.CASCADE,
                                     related_name="grants")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="выдал", null=True,
                                   on_delete=models.SET_NULL, related_name="+")
    claim = models.ForeignKey(Claim, verbose_name="по запросу", null=True, blank=True, on_delete=models.SET_NULL)
    granted_at = models.DateTimeField("выдано", auto_now_add=True)
    revoked_at = models.DateTimeField("отозвано", null=True, blank=True)

    class Meta:
        verbose_name = "право на событие"
        verbose_name_plural = "права на события"
