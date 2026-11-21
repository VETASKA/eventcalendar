"""Moderation in Django Admin (spec §5): the queue, per-card actions and confirmed bulk approval."""
from django import forms
from django.contrib import admin, messages
from django.db.models import Count, Q
from django.template.response import TemplateResponse
from django.utils.html import format_html

from . import services
from .models import Event, EventRevision, EventTranslation, EventType, Occurrence, SitePublication, Topic

FLAG_LABELS = {
    "no_title": "немає назви", "no_date": "немає дати", "no_format": "формат?", "no_type": "тип?",
    "country_unknown": "країна?", "city_unknown": "місто не знайдено", "city_ambiguous": "місто неоднозначне",
    "removed_in_source": "видалено в джерелі",
}


class OccurrenceInline(admin.TabularInline):
    model = Occurrence
    extra = 0
    fields = ("start_date", "end_date", "precision", "starts_at", "ends_at", "timezone", "city", "venue", "status",
              "source_key")
    readonly_fields = ("source_key",)
    autocomplete_fields = ("city",)


class PublicationInline(admin.TabularInline):
    model = SitePublication
    extra = 0
    fields = ("site", "status", "first_published_at", "blocked", "featured_from", "featured_to", "reason")
    readonly_fields = ("first_published_at",)


class TranslationInline(admin.TabularInline):
    model = EventTranslation
    extra = 0


class RevisionInline(admin.TabularInline):
    model = EventRevision
    extra = 0
    fields = ("origin", "status", "priority", "changes", "created_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True


class FlagFilter(admin.SimpleListFilter):
    title = "що перевірити"
    parameter_name = "flag"

    def lookups(self, request, model_admin):
        return list(FLAG_LABELS.items())

    def queryset(self, request, qs):
        return qs.filter(review_flags__contains=[self.value()]) if self.value() else qs


class SourceFilter(admin.SimpleListFilter):
    title = "джерело"
    parameter_name = "source"

    def lookups(self, request, model_admin):
        from apps.intake.models import EventSource
        return [(s.code, s.name) for s in EventSource.objects.all()]

    def queryset(self, request, qs):
        return qs.filter(intake_items__source__code=self.value()).distinct() if self.value() else qs


class UaSignalFilter(admin.SimpleListFilter):
    title = "зв'язок з Україною"
    parameter_name = "ua"

    def lookups(self, request, model_admin):
        return [("yes", "є сигнал"), ("no", "немає сигналу")]

    def queryset(self, request, qs):
        q = Q(geo_signals__country_ua=True) | Q(geo_signals__ua_phone=True) | Q(geo_signals__lang_uk=True)
        return qs.filter(q) if self.value() == "yes" else qs.exclude(q) if self.value() == "no" else qs


class EventForm(forms.ModelForm):
    expected_revision = forms.IntegerField(widget=forms.HiddenInput, required=False)

    class Meta:
        model = Event
        exclude = ("manual_fields", "revision")

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        if self.instance.pk:
            self.fields["expected_revision"].initial = self.instance.revision


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    form = EventForm
    list_display = ("title", "first_date", "city_name", "country", "state", "flags", "pending_revisions")
    list_filter = ("state", FlagFilter, SourceFilter, UaSignalFilter, "country", "format", "event_type")
    search_fields = ("title", "organizer_name", "source_url")
    date_hierarchy = "created_at"
    filter_horizontal = ("topics",)
    readonly_fields = ("state", "geo_signals", "review_flags", "organizer_verified", "created_at", "updated_at")
    inlines = [OccurrenceInline, PublicationInline, TranslationInline, RevisionInline]
    actions = ["bulk_approve", "bulk_reject"]

    def get_queryset(self, request):
        return (super().get_queryset(request).select_related("country")
                .annotate(_pending=Count("revisions", filter=Q(revisions__status="proposed")))
                .prefetch_related("occurrences__city"))

    @admin.display(description="дата")
    def first_date(self, obj):
        o = next(iter(obj.occurrences.all()), None)
        return o.start_date if o else "—"

    @admin.display(description="місто")
    def city_name(self, obj):
        o = next(iter(obj.occurrences.all()), None)
        return o.city if o and o.city_id else "—"

    @admin.display(description="перевірити")
    def flags(self, obj):
        return ", ".join(FLAG_LABELS.get(f, f) for f in obj.review_flags) or "—"

    @admin.display(description="пропозиції", ordering="_pending")
    def pending_revisions(self, obj):
        return format_html("<b>{}</b>", obj._pending) if obj._pending else ""

    def save_model(self, request, obj, form, change):
        if not change:
            obj.state = "pending"
            return super().save_model(request, obj, form, change)
        data = {k: form.cleaned_data[k] for k in form.changed_data
                if k in form.cleaned_data and k not in ("expected_revision", "topics")}
        expected = form.cleaned_data.get("expected_revision") or obj.revision
        try:
            services.save_moderator_edit(obj, data, request.user, expected_revision=expected)
        except services.PublishError as e:      # someone saved first: keep their version, tell the moderator
            self.message_user(request, f"Не збережено: {e}. Відкрийте картку знову.", messages.ERROR)

    @admin.action(description="Схвалити вибрані (з підтвердженням)")
    def bulk_approve(self, request, queryset):
        if request.POST.get("confirm") != "yes":
            return TemplateResponse(request, "admin/catalog/confirm_bulk_approve.html", {
                **self.admin_site.each_context(request), "events": queryset, "count": queryset.count(),
                "action": "bulk_approve", "opts": self.model._meta,
            })
        ok, failed = 0, []
        for event in queryset:
            pubs = event.publications.select_related("site").filter(status="pending", blocked=False)
            if not pubs:
                failed.append(f"«{event}»: немає сайту, що очікує рішення")
            for pub in pubs:
                try:
                    services.approve(event, pub.site, request.user, reason="bulk")
                    ok += 1
                except services.PublishError as e:
                    failed.append(f"«{event}» на {pub.site.code}: {e}")
        self.message_user(request, f"Опубліковано: {ok}", messages.SUCCESS if ok else messages.INFO)
        for f in failed[:50]:
            self.message_user(request, f, messages.WARNING)
        if len(failed) > 50:
            self.message_user(request, f"…та ще {len(failed) - 50} з помилками", messages.WARNING)

    @admin.action(description="Відхилити вибрані (причина: не підходить)")
    def bulk_reject(self, request, queryset):
        n = 0
        for event in queryset:
            for pub in event.publications.select_related("site").exclude(status="rejected"):
                services.reject(event, pub.site, request.user, reason="bulk: не підходить")
                n += 1
        self.message_user(request, f"Відхилено публікацій: {n}")


@admin.register(EventRevision)
class EventRevisionAdmin(admin.ModelAdmin):
    list_display = ("event", "origin", "status", "priority", "created_at")
    list_filter = ("status", "origin", "priority")
    raw_id_fields = ("event", "source_item")


@admin.register(Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("code", "names", "position", "is_active")


@admin.register(EventType)
class EventTypeAdmin(admin.ModelAdmin):
    list_display = ("code", "names", "position", "is_active")
