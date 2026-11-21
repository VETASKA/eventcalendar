from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    actor_label = models.CharField(max_length=120, blank=True, help_text="system / harvey / …")
    action = models.CharField(max_length=60, db_index=True)
    object_type = models.CharField(max_length=60)
    object_id = models.CharField(max_length=60)
    reason = models.TextField(blank=True)
    data = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-at"]


def log(action: str, obj, *, actor=None, actor_label: str = "", reason: str = "", **data) -> AuditLog:
    return AuditLog.objects.create(
        action=action, object_type=obj._meta.label_lower, object_id=str(obj.pk),
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        actor_label=actor_label or (getattr(actor, "username", "") if actor else "system"),
        reason=reason, data=data)
