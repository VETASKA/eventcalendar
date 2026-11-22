"""Moderation in the admin (spec §5): the queue, per-card actions and confirmed bulk approval."""
from django import forms
from django.contrib import admin, messages
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from unfold.decorators import display

from . import services
from .models import (Event, EventRevision, EventTranslation, EventType, Occurrence, SitePublication, TicketLink,
                     Topic)

FLAG_LABELS = {
    "no_title": "нет названия", "no_date": "нет даты", "no_format": "нет формата", "no_type": "нет типа",
    "country_unknown": "страна?", "city_unknown": "город не найден", "city_ambiguous": "город неоднозначен",
    "removed_in_source": "удалено в источнике", "from_visitor": "предложено посетителем",
    "check_title": "уточнить название", "fetch_failed": "сайт не ответил",
    "more_sessions": "в источнике несколько сеансов",
}
STATE_COLORS = {"draft": "info", "pending": "warning", "approved": "success", "rejected": "danger",
                "withdrawn": "danger"}


class NullsLast(F):
    """Column sort where cards with no value go to the end in both directions."""

    def asc(self, **kw):
        return super().asc(nulls_last=True)

    def desc(self, **kw):
        return super().desc(nulls_last=True)


class OccurrenceInline(TabularInline):
    model = Occurrence
    extra = 0
    fields = ("start_date", "end_date", "precision", "starts_at", "ends_at", "city", "venue", "status")
    autocomplete_fields = ("city",)
    tab = True


class TicketLinkInline(TabularInline):
    model = TicketLink
    extra = 0
    fields = ("position", "label", "url", "price_text", "is_active")
    ordering_field = "position"
    hide_ordering_field = True
    tab = True


class PublicationInline(TabularInline):
    model = SitePublication
    extra = 0
    fields = ("site", "status", "first_published_at", "blocked", "featured_from", "featured_to", "reason")
    readonly_fields = ("first_published_at",)
    tab = True


class TranslationInline(TabularInline):
    model = EventTranslation
    extra = 0
    tab = True


class RevisionInline(TabularInline):
    model = EventRevision
    extra = 0
    fields = ("origin", "status", "priority", "changes", "created_at")
    readonly_fields = fields
    can_delete = False
    show_change_link = True
    tab = True


class FlagFilter(admin.SimpleListFilter):
    title = "что проверить"
    parameter_name = "flag"

    def lookups(self, request, model_admin):
        return list(FLAG_LABELS.items())

    def queryset(self, request, qs):
        return qs.filter(review_flags__contains=[self.value()]) if self.value() else qs


class SourceFilter(admin.SimpleListFilter):
    title = "источник"
    parameter_name = "source"

    def lookups(self, request, model_admin):
        from apps.intake.models import EventSource
        return [(s.code, s.name) for s in EventSource.objects.all()]

    def queryset(self, request, qs):
        return qs.filter(intake_items__source__code=self.value()).distinct() if self.value() else qs


class SiteFilter(admin.SimpleListFilter):
    title = "сайт"
    parameter_name = "site"

    def lookups(self, request, model_admin):
        from apps.portals.models import Site
        return [(s.code, s.name) for s in Site.objects.all()] + [("none", "ни на одном (другие страны)")]

    def queryset(self, request, qs):
        if self.value() == "none":
            return qs.filter(publications__isnull=True)
        return qs.filter(publications__site__code=self.value()).distinct() if self.value() else qs


class UaSignalFilter(admin.SimpleListFilter):
    title = "связь с Украиной"
    parameter_name = "ua"

    def lookups(self, request, model_admin):
        return [("yes", "есть признак"), ("no", "нет признаков")]

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
class EventAdmin(ModelAdmin):
    form = EventForm
    list_display = ("title_link", "first_date", "city_name", "country_name", "format", "event_type", "state_badge",
                    "flags", "pending_revisions")
    # filled straight in the list, then one «Сохранить» for the whole page; no need to open each card
    list_editable = ("format", "event_type")
    list_display_links = None
    list_filter = ("state", FlagFilter, SiteFilter, SourceFilter, UaSignalFilter, "country", "format", "event_type")
    list_filter_sheet = True
    list_per_page = 100
    search_fields = ("title", "organizer_name", "source_url")
    date_hierarchy = "created_at"
    autocomplete_fields = ("topics", "event_type")
    readonly_fields = ("state", "geo_signals_view", "flags", "organizer_verified", "created_at", "updated_at",
                       "source_hint")
    inlines = [OccurrenceInline, TicketLinkInline, PublicationInline, TranslationInline, RevisionInline]
    actions = ["bulk_approve", "bulk_reject"]
    fieldsets = (
        ("Главное", {"fields": ("title", "source_hint", "summary", ("format", "event_type"), "topics", "state",
                                "flags")}),
        ("Ссылки и цена", {"fields": ("source_url", "registration_url", "tickets_mode", "price_text",
                                       "original_language"),
                            "description": "Несколько сервисов продажи билетов — во вкладке «Билетные сервисы». "
                                           "Если их нет, на странице будет кнопка «Регистрация / билеты»."}),
        ("Организатор", {"fields": (("organizer_name", "organizer_site"), "organization", "organizer_verified")}),
        ("География", {"fields": ("country", "geo_signals_view", "geo_reason")}),
        ("Служебное", {"classes": ["collapse"], "fields": ("created_at", "updated_at", "expected_revision")}),
    )

    def get_changelist_form(self, request, **kwargs):
        """Plain, wide dropdowns in the list (no autocomplete / «add type» buttons), choices loaded once."""
        types = [("", "— тип —")] + [(t.pk, str(t)) for t in EventType.objects.filter(is_active=True)]
        fmts = [("", "— формат —")] + list(Event.FORMAT)
        style = {"style": "min-width:150px", "class": "border border-base-200 dark:border-base-700 bg-white "
                 "dark:bg-base-900 rounded-default px-3 py-2 text-font-default-light dark:text-font-default-dark"}

        class ListForm(forms.ModelForm):
            format = forms.ChoiceField(choices=fmts, required=False, widget=forms.Select(attrs=style))
            event_type = forms.TypedChoiceField(choices=types, required=False, coerce=int, empty_value=None,
                                                widget=forms.Select(attrs=style))

            class Meta:
                model = Event
                fields = ("format", "event_type")

            def clean_event_type(self):
                v = self.cleaned_data["event_type"]
                return EventType.objects.get(pk=v) if v else None

        return ListForm

    def get_queryset(self, request):
        first = Occurrence.objects.filter(event=OuterRef("pk")).order_by("start_date", "starts_at", "id")
        return (super().get_queryset(request).select_related("country")
                .annotate(_pending=Count("revisions", filter=Q(revisions__status="proposed"), distinct=True),
                          _first_date=Subquery(first.values("start_date")[:1]),
                          _city=Subquery(first.values("city__name")[:1]),
                          _country=KeyTextTransform("uk", "country__names"))
                .prefetch_related("occurrences__city"))

    @display(description="название", ordering="title")
    def title_link(self, obj):
        from django.urls import reverse
        return format_html('<a class="font-medium text-primary-700 dark:text-primary-300" href="{}">{}</a>',
                           reverse("admin:catalog_event_change", args=[obj.pk]), obj.title)

    @display(description="дата", ordering=NullsLast("_first_date"))
    def first_date(self, obj):
        return obj._first_date.strftime("%d.%m.%Y") if obj._first_date else "—"

    @display(description="город", ordering=NullsLast("_city"))
    def city_name(self, obj):
        return obj._city or "—"

    @display(description="страна", ordering=NullsLast("_country"))
    def country_name(self, obj):
        return obj._country or "—"

    @display(description="статус", ordering="state", label=STATE_COLORS)
    def state_badge(self, obj):
        return obj.state, obj.get_state_display()

    @display(description="что проверить")
    def flags(self, obj):
        if not obj.review_flags:
            return "—"
        return format_html_join(
            " ", '<span class="inline-block rounded-default px-2 py-0.5 text-xs bg-base-100 '
                 'dark:bg-base-800 whitespace-nowrap">{}</span>',
            ((FLAG_LABELS.get(f, f),) for f in obj.review_flags))

    @display(description="описание в источнике")
    def source_hint(self, obj):
        """The source's own text, for writing a short summary in our words (it is never published as is)."""
        hints = [i.normalized.get("hint_description") for i in obj.intake_items.all() if i.normalized]
        text = next((h for h in hints if h), "")
        return format_html('<div class="text-sm text-font-subtle-light dark:text-font-subtle-dark max-w-3xl">{}</div>',
                           text) if text else "—"

    @display(description="признаки географии")
    def geo_signals_view(self, obj):
        names = {"country_ua": "страна UA", "ua_phone": "украинский телефон", "lang_uk": "анонс на украинском",
                 "tld": "домен"}
        parts = [f"{names.get(k, k)}: {v}" if not isinstance(v, bool) else names.get(k, k)
                 for k, v in obj.geo_signals.items() if v]
        return ", ".join(parts) or "—"

    @display(description="изменения", ordering="_pending")
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
            self.message_user(request, f"Не сохранено: {e}. Откройте карточку заново.", messages.ERROR)

    @admin.action(description="Одобрить выбранные (с подтверждением)")
    def bulk_approve(self, request, queryset):
        if request.POST.get("confirm") != "yes":
            return TemplateResponse(request, "admin/catalog/confirm_bulk_approve.html", {
                **self.admin_site.each_context(request), "events": queryset, "count": queryset.count(),
                "action": "bulk_approve", "opts": self.model._meta, "title": "Подтвердите публикацию",
            })
        ok, failed = 0, []
        for event in queryset:
            pubs = event.publications.select_related("site").filter(status="pending", blocked=False)
            if not pubs:
                failed.append(f"«{event}»: нет сайта, ждущего решения")
            for pub in pubs:
                try:
                    services.approve(event, pub.site, request.user, reason="массово")
                    ok += 1
                except services.PublishError as e:
                    failed.append(f"«{event}» на {pub.site.code}: {e}")
        self.message_user(request, f"Опубликовано: {ok}", messages.SUCCESS if ok else messages.INFO)
        for f in failed[:50]:
            self.message_user(request, f, messages.WARNING)
        if len(failed) > 50:
            self.message_user(request, f"…и ещё {len(failed) - 50} с ошибками", messages.WARNING)

    @admin.action(description="Отклонить выбранные (не подходят)")
    def bulk_reject(self, request, queryset):
        n = 0
        for event in queryset:
            for pub in event.publications.select_related("site").exclude(status="rejected"):
                services.reject(event, pub.site, request.user, reason="массово: не подходит")
                n += 1
        self.message_user(request, f"Отклонено публикаций: {n}")


@admin.register(EventRevision)
class EventRevisionAdmin(ModelAdmin):
    list_display = ("event", "origin", "status", "priority", "created_at")
    list_filter = ("status", "origin", "priority")
    raw_id_fields = ("event", "source_item")


@admin.register(Topic)
class TopicAdmin(ModelAdmin):
    list_display = ("code", "name_uk", "position", "is_active")
    search_fields = ("code", "names__uk")
    list_editable = ("position", "is_active")

    @display(description="название")
    def name_uk(self, obj):
        return obj.names.get("uk", "")


@admin.register(EventType)
class EventTypeAdmin(TopicAdmin):
    pass
