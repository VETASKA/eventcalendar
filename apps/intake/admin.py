from django.contrib import admin, messages
from django.db import transaction
from unfold.admin import ModelAdmin

from .models import EventSource, IntakeItem
from .services import process


@admin.register(EventSource)
class EventSourceAdmin(ModelAdmin):
    list_display = ("code", "name", "is_active", "trusted", "last_seen_at")
    exclude = ("token_hash",)


@admin.register(IntakeItem)
class IntakeItemAdmin(ModelAdmin):
    list_display = ("__str__", "url", "status", "initial_load", "removed_in_source", "event", "last_received_at")
    list_filter = ("source", "status", "initial_load", "removed_in_source")
    search_fields = ("external_id", "url", "normalized_url")
    readonly_fields = [f.name for f in IntakeItem._meta.fields]
    actions = ["reprocess"]

    def has_add_permission(self, request):
        return False

    @admin.action(description="Обработать повторно")
    def reprocess(self, request, queryset):
        for item in queryset:
            with transaction.atomic():
                process(IntakeItem.objects.select_for_update().get(pk=item.pk))
        self.message_user(request, f"Обработано: {queryset.count()}", messages.SUCCESS)
