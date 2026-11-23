"""Moderation in the admin (spec §5): the queue, per-card actions and confirmed bulk approval."""
from django import forms
from django.contrib import admin, messages
from django.db.models import Count, F, OuterRef, Q, Subquery
from django.db.models.fields.json import KeyTextTransform
from django.template.response import TemplateResponse
from django.utils.html import format_html, format_html_join
from unfold.admin import ModelAdmin, TabularInline
from django.shortcuts import redirect
from unfold.decorators import action, display

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

    def changelist_view(self, request, extra_context=None):
        # A moderator picks format/type in the list and presses an action right away: save those picks first,
        # otherwise «Одобрить» would see the old empty values.
        if request.method == "POST" and request.POST.get("action") and "_save" not in request.POST \
                and "form-TOTAL_FORMS" in request.POST:
            n = self._save_list_edits(request)
            if n:
                self.message_user(request, f"Сохранено изменений в списке: {n}", messages.SUCCESS)
        return super().changelist_view(request, extra_context)

    def _save_list_edits(self, request) -> int:
        FormSet = self.get_changelist_formset(request)
        prefix = FormSet.get_default_prefix()
        formset = FormSet(request.POST, request.FILES, prefix=prefix,
                          queryset=self._get_list_editable_queryset(request, prefix))
        if not formset.is_valid():
            return 0
        n = 0
        for form in formset.forms:
            if form.has_changed():
                obj = self.save_form(request, form, change=True)
                self.save_model(request, obj, form, change=True)
                n += 1
        return n

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


FIELD_NAMES = {"title": "название", "summary": "анонс", "format": "формат", "event_type": "тип",
               "registration_url": "регистрация", "price_text": "цена", "organizer_name": "организатор",
               "organizer_site": "сайт организатора", "source_url": "источник", "original_language": "язык",
               "occurrences": "сеансы", "_removed_in_source": "удалено в источнике"}


def _session_line(s: dict) -> str:
    from apps.geo.models import City
    city = City.objects.filter(pk=s.get("city_id")).first() if s.get("city_id") else None
    when = s.get("start_date", "")
    if s.get("end_date") and s.get("end_date") != s.get("start_date"):
        when += f" — {s['end_date']}"
    if s.get("starts_at"):
        when += " " + str(s["starts_at"])[11:16]
    status = dict(Occurrence.STATUS).get(s.get("status") or "scheduled", "")
    parts = [when, city.name if city else "", s.get("venue", ""), status if s.get("status") not in (None, "scheduled") else ""]
    line = " · ".join(p for p in parts if p)
    return ("<s>" + line + "</s>  (удалить)") if s.get("deleted") else line


@admin.register(EventRevision)
class EventRevisionAdmin(ModelAdmin):
    list_display = ("created_at", "event_link", "origin", "author", "what", "status_badge", "priority")
    list_display_links = ("created_at", "what")
    list_filter = ("status", "origin", "priority")
    readonly_fields = ("event", "origin", "author", "status", "created_at", "decided_at", "diff")
    fields = ("event", "origin", "author", "status", "created_at", "decided_at", "diff")
    actions = ["apply", "reject"]
    actions_detail = ["apply_one", "reject_one"]
    ordering = ("-priority", "-created_at")

    @action(description="Применить", url_path="apply-one")
    def apply_one(self, request, object_id):
        rev = EventRevision.objects.get(pk=object_id)
        try:
            services.apply_revision(rev, request.user)
            self.message_user(request, "Изменение применено", messages.SUCCESS)
        except services.PublishError as e:
            self.message_user(request, str(e), messages.WARNING)
        return redirect("admin:catalog_eventrevision_changelist")

    @action(description="Отклонить", url_path="reject-one")
    def reject_one(self, request, object_id):
        services.reject_revision(EventRevision.objects.get(pk=object_id), request.user)
        self.message_user(request, "Изменение отклонено")
        return redirect("admin:catalog_eventrevision_changelist")

    def has_add_permission(self, request):
        return False

    @display(description="событие")
    def event_link(self, obj):
        return format_html('<a class="text-primary-700 dark:text-primary-300" href="/admin/catalog/event/{}/change/">{}</a>',
                           obj.event_id, obj.event)

    @display(description="что меняется")
    def what(self, obj):
        return ", ".join(FIELD_NAMES.get(k, k) for k in obj.changes)

    @display(description="статус", ordering="status",
             label={"proposed": "warning", "approved": "success", "rejected": "danger", "superseded": "info"})
    def status_badge(self, obj):
        return obj.status, obj.get_status_display()

    @display(description="было → станет")
    def diff(self, obj):
        e = obj.event
        rows = []
        for k, v in obj.changes.items():
            if k == "occurrences":
                old = "<br>".join(_session_line({"start_date": str(o.start_date), "end_date": str(o.end_date),
                                                 "starts_at": o.starts_at.isoformat() if o.starts_at else None,
                                                 "city_id": o.city_id, "venue": o.venue, "status": o.status})
                                  for o in e.occurrences.all())
                new = "<br>".join(_session_line(x) for x in v)
            elif k == "event_type":
                old, new = str(e.event_type or "—"), str(EventType.objects.filter(code=v).first() or v)
            elif k == "_removed_in_source":
                old, new = "есть в источнике", "событие удалено в источнике — снять с публикации?"
            else:
                old, new = getattr(e, k, ""), v
            rows.append(format_html('<tr><td class="pr-4 py-2 font-semibold align-top">{}</td>'
                                    '<td class="pr-4 py-2 align-top text-font-subtle-light dark:text-font-subtle-dark">{}</td>'
                                    '<td class="py-2 align-top">{}</td></tr>',
                                    FIELD_NAMES.get(k, k), format_html(str(old or "—")) if k == "occurrences" else old or "—",
                                    format_html(str(new or "—")) if k == "occurrences" else new or "—"))
        return format_html('<table class="text-sm"><tr><th></th><th class="text-left pr-4">было</th>'
                           '<th class="text-left">станет</th></tr>{}</table>', format_html("".join(rows)))

    @admin.action(description="Применить выбранные изменения")
    def apply(self, request, queryset):
        ok, failed = 0, []
        for rev in queryset.filter(status="proposed"):
            try:
                services.apply_revision(rev, request.user)
                ok += 1
            except services.PublishError as e:
                failed.append(f"«{rev.event}»: {e}")
        self.message_user(request, f"Применено: {ok}", messages.SUCCESS if ok else messages.INFO)
        for f in failed:
            self.message_user(request, f, messages.WARNING)

    @admin.action(description="Отклонить выбранные изменения")
    def reject(self, request, queryset):
        n = 0
        for rev in queryset.filter(status="proposed"):
            services.reject_revision(rev, request.user)
            n += 1
        self.message_user(request, f"Отклонено: {n}")


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
