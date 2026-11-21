"""Organizers and their rights on events (spec §6). Logic comes in stage 4; the tables exist now."""
from django.conf import settings
from django.db import models


class Organization(models.Model):
    name = models.CharField(max_length=300)
    website = models.URLField(max_length=500, blank=True)
    official_host = models.CharField(max_length=253, blank=True, help_text="Підтверджений HTTPS-хост")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


class Membership(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, default="member")   # owner | member

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization", "user"], name="uniq_membership")]


class Claim(models.Model):
    METHOD = [("file", "файл на сайті"), ("email", "корпоративна пошта"), ("manual", "ручний розгляд")]
    STATUS = [("open", "відкрито"), ("verified", "контроль підтверджено"), ("approved", "права видано"),
              ("rejected", "відхилено"), ("expired", "прострочено")]
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    event = models.ForeignKey("catalog.Event", on_delete=models.CASCADE, related_name="claims")
    organization = models.ForeignKey(Organization, null=True, blank=True, on_delete=models.SET_NULL)
    method = models.CharField(max_length=8, choices=METHOD)
    host = models.CharField(max_length=253, blank=True)
    verify_path = models.CharField(max_length=500, blank=True)
    token_hash = models.CharField(max_length=64, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS, default="open")
    evidence = models.TextField(blank=True)
    decision_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class EventGrant(models.Model):
    event = models.ForeignKey("catalog.Event", on_delete=models.CASCADE, related_name="grants")
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name="grants")
    granted_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    claim = models.ForeignKey(Claim, null=True, blank=True, on_delete=models.SET_NULL)
    granted_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
