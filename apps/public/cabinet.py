"""Visitor and organizer actions on the public site: error reports, sign-in, «Це моя подія», the cabinet."""
import zoneinfo
from datetime import datetime
from urllib.parse import urlsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core import signing
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils import timezone as tz
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.catalog.models import Event, EventRevision
from apps.core.i18n import lang, lurl
from apps.core.mail import send
from apps.core.ratelimit import allow, ip_hash
from apps.geo.models import City
from apps.organizers.models import Claim, Profile
from apps.organizers.services import user_events
from apps.organizers.verification import (FILE_NAME, check_file, corporate_ok, event_host, file_token,
                                          make_email_link_token, mark_verified, token_expired, use_email_link_token)

from .forms import (ClaimForm, ClaimMethodMixin, CorporateEmailForm, ErrorReportForm, LoginForm, OrganizerEventForm,
                    RegisterForm, SessionFormSet)


def _published_event(request, pk) -> Event:
    e = Event.objects.filter(pk=pk, publications__site=request.site, publications__status="published").first()
    if e is None:
        raise Http404
    return e


def _url(e: Event) -> str:
    return lurl(f"/events/{e.pk}-{e.slug}/")


def _next(request, default=None) -> str:
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    ok = nxt.startswith("/") and url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()})
    return nxt if ok else (default or lurl("/cabinet/"))


# ── «Знайшли помилку?» ───────────────────────────────────────────────────────

@require_POST
def report_error(request, pk):
    e = _published_event(request, pk)
    form = ErrorReportForm(request.POST)
    if form.is_bot():
        messages.success(request, _("Дякуємо! Повідомлення надіслано модератору."))
        return redirect(_url(e))
    if not allow(request, "report", limit=10):
        messages.error(request, _("Забагато повідомлень. Спробуйте пізніше."))
        return redirect(_url(e))
    if not form.is_valid():
        messages.error(request, _("Опишіть, будь ласка, що саме не так."))
        return redirect(_url(e) + "#report")
    r = form.save(commit=False)
    r.event, r.site, r.ip_hash = e, request.site, ip_hash(request)
    r.user = request.user if request.user.is_authenticated else None
    r.save()
    messages.success(request, _("Дякуємо! Повідомлення надіслано модератору."))
    return redirect(_url(e))


# ── sign in / register ───────────────────────────────────────────────────────

def login_view(request):
    nxt = _next(request)
    if request.user.is_authenticated:
        return redirect(nxt)
    form, reg = LoginForm(request.POST or None), RegisterForm()
    if request.method == "POST":
        if not allow(request, "login", limit=20):
            messages.error(request, _("Забагато спроб входу. Спробуйте за годину."))
        elif form.is_valid():
            user = authenticate(request, username=form.cleaned_data["email"].strip().lower(),
                                password=form.cleaned_data["password"])
            if user is not None:
                login(request, user)
                return redirect(nxt)
            form.add_error(None, _("Невірний email або пароль."))
    return render(request, "public/login.html", {"form": form, "reg": reg, "next": nxt, "tab": "login"})


def register_view(request):
    nxt = _next(request)
    if request.user.is_authenticated:
        return redirect(nxt)
    reg = RegisterForm(request.POST or None)
    if request.method == "POST":
        if reg.is_bot():
            return redirect(lurl("/"))
        if not allow(request, "register", limit=5):
            messages.error(request, _("Забагато реєстрацій з цієї адреси. Спробуйте пізніше."))
        elif reg.is_valid():
            d = reg.cleaned_data
            user = User.objects.create_user(username=d["email"], email=d["email"], password=d["password"],
                                            first_name=d["name"][:150])
            profile = Profile.objects.create(user=user, lang=lang(), email_verified=not settings.MAIL_ENABLED)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            if settings.MAIL_ENABLED:
                send_verification(request, user, profile)
                messages.success(request, _("Кабінет створено. Ми надіслали лист — підтвердіть email за посиланням."))
            else:
                messages.success(request, _("Кабінет створено."))
            return redirect(nxt)
    return render(request, "public/login.html", {"form": LoginForm(), "reg": reg, "next": nxt, "tab": "register"})


@require_POST
def logout_view(request):
    logout(request)
    return redirect(lurl("/"))


# ── «Це моя подія» ───────────────────────────────────────────────────────────

def claim_view(request, pk):
    e = _published_event(request, pk)
    if not request.user.is_authenticated:
        return redirect(lurl("/cabinet/login/") + "?next=" + lurl(f"/events/{e.pk}/claim/"))
    if user_events(request.user).filter(pk=e.pk).exists():
        messages.success(request, _("Ця подія вже у вашому кабінеті."))
        return redirect(lurl("/cabinet/"))
    if not Profile.of(request.user).email_verified:
        messages.error(request, _("Спочатку підтвердіть свій email — лист у пошті, або надішліть його ще раз у кабінеті."))
        return redirect(lurl("/cabinet/"))
    existing = Claim.objects.filter(user=request.user, event=e, status__in=["open", "verified"]).first()
    if existing:
        return redirect(lurl(f"/cabinet/claims/{existing.pk}/"))
    form = ClaimForm(request.POST or None)
    method_form = ClaimMethodMixin(request.POST or None)
    if not settings.MAIL_ENABLED:
        method_form.fields["method"].choices = [c for c in method_form.fields["method"].choices if c[0] != "email"]
    if request.method == "POST":
        if not allow(request, "claim", limit=10):
            messages.error(request, _("Забагато заявок. Спробуйте пізніше."))
        elif form.is_valid() and method_form.is_valid():
            claim = Claim.objects.create(user=request.user, event=e, method=method_form.cleaned_data["method"],
                                         host=event_host(e)[:253], **form.cleaned_data)
            return redirect(lurl(f"/cabinet/claims/{claim.pk}/"))
    return render(request, "public/claim.html", {"e": e, "form": form, "method_form": method_form})


@login_required
def claim_detail(request, pk):
    """The next step of a claim: put the file / confirm the corporate address / wait for the moderator."""
    claim = Claim.objects.filter(pk=pk, user=request.user).select_related("event").first()
    if claim is None:
        raise Http404
    email_form = CorporateEmailForm(request.POST or None) if claim.method == "email" else None
    if request.method == "POST" and claim.status == "open":
        action = request.POST.get("action")
        if action == "check_file":
            if not allow(request, f"claimfile:{claim.pk}", limit=10) or claim.attempts >= 20:
                messages.error(request, _("Забагато перевірок. Спробуйте пізніше."))
            else:
                Claim.objects.filter(pk=claim.pk).update(attempts=claim.attempts + 1)
                ok, why = check_file(claim)
                if ok:
                    mark_verified(claim, "file")
                    messages.success(request, _("Сайт підтверджено. Модератор видасть права найближчим часом."))
                else:
                    messages.error(request, {
                        "expired": _("Термін дії коду минув. Створіть заявку ще раз."),
                        "other_host": _("Файл знайдено на іншому сайті. Він має бути на сайті самої події."),
                        "wrong_token": _("Файл знайдено, але код у ньому не збігається."),
                    }.get(why, _("Файл не знайдено. Перевірте адресу й спробуйте ще раз за хвилину.")))
            return redirect(lurl(f"/cabinet/claims/{claim.pk}/"))
        if action == "send_email" and email_form is not None and settings.MAIL_ENABLED:
            if not allow(request, f"claimmail:{claim.pk}", limit=5):
                messages.error(request, _("Забагато листів. Спробуйте пізніше."))
            elif email_form.is_valid():
                ok, why = corporate_ok(email_form.cleaned_data["email"], claim.host)
                if not ok:
                    email_form.add_error("email", _("Потрібна адреса на домені сайту події, не публічна пошта.")
                                         if why == "public" else _("Адреса має бути на домені %(host)s.")
                                         % {"host": claim.host})
                else:
                    token = make_email_link_token(claim, email_form.cleaned_data["email"])
                    send(email_form.cleaned_data["email"], "claim_email", {
                        "event": claim.event, "link": request.build_absolute_uri(lurl(f"/cabinet/claims/confirm/{token}/"))},
                        lang=lang())
                    messages.success(request, _("Лист надіслано. Відкрийте його й перейдіть за посиланням протягом доби."))
                    return redirect(lurl(f"/cabinet/claims/{claim.pk}/"))
    return render(request, "public/claim_detail.html", {
        "claim": claim, "e": claim.event, "token": file_token(claim), "file_name": FILE_NAME,
        "expired": token_expired(claim), "email_form": email_form, "mail_enabled": settings.MAIL_ENABLED})


def claim_email_confirm(request, token):
    claim, why = use_email_link_token(token)
    if claim is None:
        messages.error(request, _("Посилання недійсне або вже використане."))
        return redirect(lurl("/cabinet/"))
    mark_verified(claim, "email")
    messages.success(request, _("Пошту підтверджено. Модератор видасть права найближчим часом."))
    return redirect(lurl("/cabinet/"))


# ── email confirmation ───────────────────────────────────────────────────────

def send_verification(request, user, profile=None) -> None:
    token = signing.dumps({"u": user.pk, "e": user.email}, salt="verify-email")
    send(user.email, "verify_email", {"user": user,
                                      "link": request.build_absolute_uri(lurl(f"/cabinet/verify/{token}/"))},
         lang=(profile or Profile.of(user)).lang)


def verify_email_view(request, token):
    try:
        data = signing.loads(token, salt="verify-email", max_age=3 * 24 * 3600)
    except signing.BadSignature:
        messages.error(request, _("Посилання недійсне або застаріле. Надішліть лист ще раз у кабінеті."))
        return redirect(lurl("/cabinet/"))
    user = User.objects.filter(pk=data.get("u"), email=data.get("e")).first()
    if user is None:
        raise Http404
    p = Profile.of(user)
    if not p.email_verified:
        p.email_verified, p.email_verified_at = True, timezone.now()
        p.save(update_fields=["email_verified", "email_verified_at"])
    messages.success(request, _("Email підтверджено."))
    return redirect(lurl("/cabinet/"))


@require_POST
@login_required
def resend_verification(request):
    if not allow(request, "resend", limit=3):
        messages.error(request, _("Забагато листів. Спробуйте пізніше."))
    elif settings.MAIL_ENABLED:
        send_verification(request, request.user)
        messages.success(request, _("Лист надіслано ще раз."))
    return redirect(lurl("/cabinet/"))


# ── organizer edits ──────────────────────────────────────────────────────────

def _city_choices(event, current_ids):
    qs = City.objects.filter(is_active=True).filter(Q(importance__gte=20) | Q(pk__in=current_ids))
    if event.country_id:
        qs = qs.filter(country_id=event.country_id)
    return [(str(c.pk), c.label(lang())) for c in qs.order_by("-importance", "name")[:300]]


@login_required
def event_edit(request, pk):
    """The organizer proposes changes; a moderator applies them (EventRevision, origin «organizer»)."""
    e = user_events(request.user).filter(pk=pk).first()
    if e is None:
        raise Http404                               # someone else's event: as if it did not exist
    occs = list(e.occurrences.select_related("city").order_by("start_date", "starts_at"))
    zone = zoneinfo.ZoneInfo(occs[0].timezone if occs else "Europe/Kyiv")
    initial_sessions = [{
        "id": o.pk, "start_date": o.start_date, "end_date": o.end_date if o.end_date != o.start_date else None,
        "start_time": tz.localtime(o.starts_at, zone).time() if o.starts_at and o.precision == "datetime" else None,
        "end_time": tz.localtime(o.ends_at, zone).time() if o.ends_at and o.precision == "datetime" else None,
        "city": str(o.city_id or ""), "venue": o.venue, "status": o.status} for o in occs]
    cities = _city_choices(e, [o.city_id for o in occs if o.city_id])
    initial = {"title": e.title, "summary": e.summary, "format": e.format or "offline",
               "event_type": e.event_type.code if e.event_type_id else "", "registration_url": e.registration_url,
               "price_text": e.price_text}
    form = OrganizerEventForm(request.POST or None, initial=initial)
    sessions = SessionFormSet(request.POST or None, initial=initial_sessions, prefix="s",
                              form_kwargs={"cities": cities})
    pending = e.revisions.filter(origin="organizer", status="proposed", author=request.user).first()
    if request.method == "POST" and form.is_valid() and sessions.is_valid():
        changes = {k: v for k, v in form.cleaned_data.items() if v != initial.get(k)}
        new_sessions = []
        for f in sessions:
            d = f.cleaned_data
            if not d or not d.get("start_date"):
                continue
            if d.get("id") and d["id"] not in {o.pk for o in occs}:
                continue                            # not one of this event's sessions
            end = d.get("end_date") or d["start_date"]
            starts = ends = None
            if d.get("start_time"):
                starts = datetime.combine(d["start_date"], d["start_time"], zone).isoformat()
                if d.get("end_time"):
                    ends = datetime.combine(end, d["end_time"], zone).isoformat()
            new_sessions.append({"id": d.get("id"), "start_date": d["start_date"].isoformat(), "end_date": end.isoformat(),
                                 "starts_at": starts, "ends_at": ends, "precision": "datetime" if starts else "date",
                                 "status": d["status"], "city_id": int(d["city"]) if d.get("city") else None,
                                 "venue": d.get("venue", ""), "deleted": bool(d.get("DELETE"))})
        old = [{"id": i["id"], "start_date": i["start_date"].isoformat(),
                "end_date": (i["end_date"] or i["start_date"]).isoformat(), "status": i["status"],
                "city_id": int(i["city"]) if i["city"] else None, "venue": i["venue"],
                "starts_at": datetime.combine(i["start_date"], i["start_time"], zone).isoformat() if i["start_time"] else None}
               for i in initial_sessions]
        cmp = lambda xs: [{k: x[k] for k in ("id", "start_date", "end_date", "status", "city_id", "venue", "starts_at")}  # noqa: E731
                          for x in xs if not x.get("deleted")]
        if cmp(new_sessions) != cmp(old) or any(x.get("deleted") for x in new_sessions):
            changes["occurrences"] = new_sessions
        if not changes:
            messages.success(request, _("Змін немає."))
            return redirect(lurl("/cabinet/"))
        with transaction.atomic():
            e.revisions.filter(origin="organizer", status="proposed", author=request.user).update(
                status="superseded", decided_at=timezone.now())
            urgent = "occurrences" in changes and any(
                s["status"] != "scheduled" or s.get("deleted") for s in changes["occurrences"])
            EventRevision.objects.create(event=e, base_revision=e.revision, origin="organizer", author=request.user,
                                         changes=changes, priority=urgent or "occurrences" in changes)
        messages.success(request, _("Зміни надіслано на модерацію. Після перевірки вони зʼявляться на сайті."))
        return redirect(lurl("/cabinet/"))
    return render(request, "public/event_edit.html", {"e": e, "form": form, "sessions": sessions, "pending": pending})


@login_required
def cabinet_view(request):
    claims = (Claim.objects.filter(user=request.user).select_related("event")
              .exclude(status="approved").order_by("-created_at"))
    events = list(user_events(request.user).prefetch_related("occurrences__city", "publications"))
    pending = set(EventRevision.objects.filter(event__in=events, origin="organizer", status="proposed")
                  .values_list("event_id", flat=True))
    for e in events:
        e.has_pending = e.pk in pending
    return render(request, "public/cabinet.html", {
        "claims": claims, "events": events, "profile": Profile.of(request.user),
        "mail_enabled": settings.MAIL_ENABLED})


# ── «Запропонувати подію» ────────────────────────────────────────────────────

@require_POST
def suggest_view(request):
    import hashlib

    from apps.core.text import norm_url
    from apps.intake.models import EventSource, IntakeItem
    from apps.intake.services import receive

    from .forms import SuggestForm

    form = SuggestForm(request.POST)
    if form.is_bot():
        messages.success(request, _("Дякуємо! Подію надіслано на перевірку."))
        return redirect(lurl("/"))
    if not allow(request, "suggest", limit=10):
        messages.error(request, _("Забагато пропозицій. Спробуйте пізніше."))
        return redirect(lurl("/"))
    if not form.is_valid():
        messages.error(request, _("Вкажіть, будь ласка, коректне посилання на подію."))
        return redirect(lurl("/") + "#suggest")
    d = form.cleaned_data
    key = norm_url(d["url"])
    known = IntakeItem.objects.filter(normalized_url=key, event__isnull=False).select_related("event").first()
    if known:
        live = known.event.publications.filter(site=request.site, status="published").exists()
        messages.success(request, _("Ця подія вже є в календарі.") if live else
                         _("Дякуємо! Ця подія вже є у нас і чекає на перевірку."))
        return redirect(_url(known.event) if live else lurl("/"))
    src, _new = EventSource.objects.get_or_create(code="form", defaults={"name": "Форма «Запропонувати подію»"})
    country = next(iter(sorted(request.site.country_codes())), "")
    receive(src, {"external_id": hashlib.sha256(key.encode()).hexdigest()[:40], "url": d["url"],
                  "email": d["email"], "date": d["date"].isoformat() if d["date"] else "", "city": d["city"],
                  "type": d["type"], "country": country, "ip": ip_hash(request)[:16]})
    messages.success(request, _("Дякуємо! Подію надіслано на перевірку — після модерації вона зʼявиться в календарі."))
    return redirect(lurl("/"))


def password_reset(request, *args, **kwargs):
    """Django's reset view, limited to 5 requests an hour per address (each one sends a letter)."""
    from django.contrib.auth import views as auth
    from django.urls import reverse
    if request.method == "POST" and not allow(request, "pwreset", limit=5):
        messages.error(request, _("Забагато запитів. Спробуйте пізніше."))
        return redirect(lurl("/cabinet/password/reset/"))
    return auth.PasswordResetView.as_view(
        template_name="public/password_reset.html", email_template_name="email/password_reset.txt",
        subject_template_name="email/password_reset_subject.txt", success_url=reverse("password_reset_done"),
    )(request, *args, **kwargs)
