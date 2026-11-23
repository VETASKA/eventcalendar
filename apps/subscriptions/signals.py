"""When a published session changes date, time or status, people with a reminder hear about it."""
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from apps.catalog.models import Occurrence

WATCHED = ("start_date", "starts_at", "status")


@receiver(pre_save, sender=Occurrence)
def remember_before(sender, instance, **kwargs):
    if instance.pk:
        old = Occurrence.objects.filter(pk=instance.pk).values(*WATCHED).first()
        instance._before = old


@receiver(post_save, sender=Occurrence)
def changed(sender, instance, created, **kwargs):
    old = getattr(instance, "_before", None)
    if created or not old:
        return
    if all(old[k] == getattr(instance, k) for k in WATCHED):
        return
    if not instance.reminders.exists():
        return
    from .tasks import notify_change
    before = {"start_date": str(old["start_date"]), "starts_at": old["starts_at"].isoformat() if old["starts_at"] else "",
              "status": old["status"]}
    pk = instance.pk
    transaction.on_commit(lambda: notify_change.delay(pk, before))
