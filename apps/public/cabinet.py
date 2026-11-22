"""Visitor and organizer actions on the public site: error reports, sign-in, «Це моя подія», the cabinet."""
from urllib.parse import urlsplit

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.translation import gettext as _
from django.views.decorators.http import require_POST

from apps.catalog.models import Event
from apps.core.i18n import lurl
from apps.core.ratelimit import allow, ip_hash
from apps.organizers.models import Claim
from apps.organizers.services import user_events

from .forms import ClaimForm, ErrorReportForm, LoginForm, RegisterForm


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
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
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
    existing = Claim.objects.filter(user=request.user, event=e, status__in=["open", "verified"]).first()
    if existing:
        return render(request, "public/claim.html", {"e": e, "existing": existing})
    form = ClaimForm(request.POST or None)
    if request.method == "POST":
        if not allow(request, "claim", limit=10):
            messages.error(request, _("Забагато заявок. Спробуйте пізніше."))
        elif form.is_valid():
            Claim.objects.create(user=request.user, event=e, method="manual",
                                 host=(urlsplit(e.source_url).hostname or "")[:253], **form.cleaned_data)
            messages.success(request, _("Заявку надіслано. Модератор перевірить її і відповість у кабінеті."))
            return redirect(lurl("/cabinet/"))
    return render(request, "public/claim.html", {"e": e, "form": form})


@login_required
def cabinet_view(request):
    claims = (Claim.objects.filter(user=request.user).select_related("event")
              .exclude(status="approved").order_by("-created_at"))
    events = user_events(request.user).prefetch_related("occurrences__city", "publications")
    return render(request, "public/cabinet.html", {"claims": claims, "events": events})


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
