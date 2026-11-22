from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin
from unfold.decorators import display

from .models import ErrorReport


@admin.register(ErrorReport)
class ErrorReportAdmin(ModelAdmin):
    list_display = ("created_at", "event_link", "kind", "short", "email", "status_badge")
    list_filter = ("status", "kind", "site")
    search_fields = ("message", "email", "event__title")
    readonly_fields = ("event", "site", "kind", "message", "email", "user", "created_at")
    fields = ("event", "kind", "message", "email", "user", "created_at", "status", "note")
    actions = ["mark_done", "mark_dismissed"]

    def has_add_permission(self, request):
        return False

    @display(description="событие")
    def event_link(self, obj):
        return format_html('<a class="text-primary-700 dark:text-primary-300" href="/admin/catalog/event/{}/change/">{}</a>',
                           obj.event_id, obj.event)

    @display(description="сообщение")
    def short(self, obj):
        return (obj.message[:90] + "…") if len(obj.message) > 90 else obj.message

    @display(description="статус", ordering="status", label={"new": "warning", "done": "success", "dismissed": "info"})
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @admin.action(description="Отметить: исправлено")
    def mark_done(self, request, qs):
        self.message_user(request, f"Исправлено: {qs.update(status='done')}", messages.SUCCESS)

    @admin.action(description="Отметить: не подтвердилось")
    def mark_dismissed(self, request, qs):
        self.message_user(request, f"Закрыто: {qs.update(status='dismissed')}")
