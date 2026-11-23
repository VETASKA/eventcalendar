from django.conf import settings
from django.db import models

ACTIONS = {
    "event.imported": "событие получено из источника",
    "event.edit": "правка карточки",
    "event.withdrawn_by_source": "снято источником",
    "publication.approve": "опубликовано",
    "publication.reject": "отклонено",
    "publication.unpublish": "снято с публикации",
    "claim.approve": "права организатору выданы",
    "claim.reject": "заявка организатора отклонена",
    "grant.revoke": "права организатора отозваны",
    "revision.apply": "изменение применено",
    "revision.reject": "изменение отклонено",
}


class AuditLog(models.Model):
    at = models.DateTimeField("когда", auto_now_add=True, db_index=True)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, verbose_name="пользователь", null=True, blank=True,
                              on_delete=models.SET_NULL)
    actor_label = models.CharField("кто", max_length=120, blank=True, help_text="system / harvey / логин")
    action = models.CharField("действие", max_length=60, db_index=True)
    object_type = models.CharField("тип объекта", max_length=60)
    object_id = models.CharField("ID объекта", max_length=60)
    reason = models.TextField("причина", blank=True)
    data = models.JSONField("подробности", default=dict, blank=True)

    class Meta:
        ordering = ["-at"]
        verbose_name = "запись журнала"
        verbose_name_plural = "журнал действий"

    def action_label(self) -> str:
        return ACTIONS.get(self.action, self.action)


def log(action: str, obj, *, actor=None, actor_label: str = "", reason: str = "", **data) -> AuditLog:
    return AuditLog.objects.create(
        action=action, object_type=obj._meta.label_lower, object_id=str(obj.pk),
        actor=actor if getattr(actor, "is_authenticated", False) else None,
        actor_label=actor_label or (getattr(actor, "username", "") if actor else "system"),
        reason=reason, data=data)
