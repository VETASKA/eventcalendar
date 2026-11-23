from django.contrib import admin, messages
from django.utils.html import format_html
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from . import services
from .models import Claim, EventGrant, Membership, Organization, Profile


class MemberInline(TabularInline):
    model = Membership
    extra = 0
    raw_id_fields = ("user",)


class GrantInline(TabularInline):
    model = EventGrant
    extra = 0
    fields = ("event", "granted_at", "granted_by", "revoked_at")
    readonly_fields = ("granted_at", "granted_by")
    raw_id_fields = ("event",)


@admin.register(Organization)
class OrganizationAdmin(ModelAdmin):
    list_display = ("name", "website", "created_at")
    search_fields = ("name", "website")
    inlines = [MemberInline, GrantInline]


@admin.register(Claim)
class ClaimAdmin(ModelAdmin):
    list_display = ("created_at", "event_link", "who", "org_name", "phone", "method", "status_badge")
    list_filter = ("status",)
    search_fields = ("event__title", "user__email", "org_name", "phone")
    readonly_fields = ("user", "event", "org_name", "role", "phone", "evidence", "host", "method", "verify_email",
                       "verified_at", "created_at", "organization")
    fields = ("event", "user", "org_name", "role", "phone", "evidence", "method", "host", "verify_email", "verified_at",
              "created_at", "organization", "status", "decision_note")
    actions = ["approve", "reject"]

    def has_add_permission(self, request):
        return False

    @display(description="событие")
    def event_link(self, obj):
        return format_html('<a class="text-primary-700 dark:text-primary-300" href="/admin/catalog/event/{}/change/">{}</a>',
                           obj.event_id, obj.event)

    @display(description="кто")
    def who(self, obj):
        return f"{obj.user.first_name} <{obj.user.email}>"

    @display(description="статус", ordering="status",
             label={"open": "warning", "verified": "info", "approved": "success", "rejected": "danger", "expired": "info"})
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @admin.action(description="Одобрить: выдать права на событие")
    def approve(self, request, qs):
        n = 0
        for c in qs.exclude(status="approved"):
            services.approve_claim(c, request.user, note=c.decision_note)
            n += 1
        self.message_user(request, f"Права выданы: {n}. Событие появится в кабинете организатора.", messages.SUCCESS)

    @admin.action(description="Отклонить")
    def reject(self, request, qs):
        n = 0
        for c in qs.exclude(status__in=["approved", "rejected"]):
            services.reject_claim(c, request.user, note=c.decision_note or "Не вдалося підтвердити")
            n += 1
        self.message_user(request, f"Отклонено: {n}")

    def save_model(self, request, obj, form, change):
        # status changed by hand in the form → go through the same rules as the actions
        if change and "status" in form.changed_data:
            new = obj.status
            obj.status = form.initial.get("status")
            super().save_model(request, obj, form, change)
            if new == "approved":
                services.approve_claim(obj, request.user, note=obj.decision_note)
                return
            if new == "rejected":
                services.reject_claim(obj, request.user, note=obj.decision_note or "Не вдалося підтвердити")
                return
            obj.status = new
        super().save_model(request, obj, form, change)


@admin.register(EventGrant)
class EventGrantAdmin(ModelAdmin):
    list_display = ("event", "organization", "granted_at", "revoked_at")
    raw_id_fields = ("event", "organization", "claim")


admin.site.register(Membership, ModelAdmin)


@admin.register(Profile)
class ProfileAdmin(ModelAdmin):
    list_display = ("user", "email_verified", "lang")
    list_filter = ("email_verified", "lang")
    search_fields = ("user__email",)
    actions = ["mark_verified"]

    @admin.action(description="Отметить email подтверждённым")
    def mark_verified(self, request, qs):
        self.message_user(request, f"Подтверждено: {qs.update(email_verified=True)}")
