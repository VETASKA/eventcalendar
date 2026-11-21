from django.contrib import admin
from unfold.admin import ModelAdmin
from unfold.decorators import display

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(ModelAdmin):
    list_display = ("at", "actor_label", "action_name", "object_type", "object_id", "reason")
    list_filter = ("action", "object_type")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    @display(description="действие", ordering="action")
    def action_name(self, obj):
        return obj.action_label()

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
