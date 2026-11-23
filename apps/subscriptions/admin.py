from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import display

from .models import Announcement, Delivery, Reminder, Subscription


@admin.register(Subscription)
class SubscriptionAdmin(ModelAdmin):
    """Contacts are shown masked in lists; the full address only on the record itself."""
    list_display = ("masked_address", "channel", "site", "status", "digest", "interests", "lang", "created_at")
    list_filter = ("site", "channel", "status", "digest", "lang")
    search_fields = ("address",)
    readonly_fields = ("consent_at", "consent_source", "created_at", "last_digest_at", "link_token")

    @display(description="адрес")
    def masked_address(self, obj):
        return obj.masked()

    @display(description="интересы")
    def interests(self, obj):
        f = obj.filters or {}
        return f"городов: {len(f.get('city', []))}, категорий: {len(f.get('type', []))}" if f else "всё"


@admin.register(Delivery)
class DeliveryAdmin(ModelAdmin):
    list_display = ("created_at", "kind", "status", "attempts", "sent_at", "error")
    list_filter = ("kind", "status")
    readonly_fields = [f.name for f in Delivery._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(Reminder)
class ReminderAdmin(ModelAdmin):
    list_display = ("occurrence", "send_at", "status")
    list_filter = ("status",)
    raw_id_fields = ("subscription", "occurrence")


@admin.register(Announcement)
class AnnouncementAdmin(ModelAdmin):
    list_display = ("event", "site", "created_at", "suppressed", "digested_at")
    list_filter = ("site", "suppressed")
    raw_id_fields = ("event",)
