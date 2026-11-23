"""Public side of subscriptions: subscribe, confirm, unsubscribe in one click, «remind me», Telegram webhook."""
import hmac
import json
import secrets

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.translation import gettext as _
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from apps.catalog.models import EventType, Occurrence
from apps.core.i18n import lang, lurl, name_in
from apps.core.mail import site_url
from apps.core.ratelimit import allow, ip_hash
from apps.geo.models import City

from . import telegram
from .delivery import deliver
from .forms import RemindForm, SubscribeForm
from .models import Reminder, Subscription
from .services import reminder_time
from .tokens import confirm_token, read_confirm, read_unsubscribe


def subscribe_choices():
    cities = [(str(c.pk), c.label(lang())) for c in City.objects.filter(is_active=True, importance__gte=20)
              .order_by("-importance", "name")]
    types = [(t.code, name_in(t.names, fallback=t.code)) for t in EventType.objects.filter(is_active=True)]
    return cities, types


def _send_confirm(request, sub, filters, digest, reminder_id=None):
    token = confirm_token(sub, filters, digest, reminder_id)
    link = request.build_absolute_uri(lurl(f"/subscribe/confirm/{token}/"))
    deliver(sub, "confirm", f"confirm:{sub.pk}:{token[-24:]}", "subscribe_confirm",
            {"link": link, "filters_text": _filters_text(filters), "reminder": reminder_id is not None})


def _filters_text(f: dict) -> str:
    parts = []
    if f.get("city"):
        parts.append(", ".join(c.label(lang()) for c in City.objects.filter(pk__in=f["city"])))
    if f.get("type"):
        parts.append(", ".join(name_in(t.names, fallback=t.code) for t in EventType.objects.filter(code__in=f["type"])))
    return " · ".join(parts)


@require_POST
def subscribe(request):
    cities, types = subscribe_choices()
    form = SubscribeForm(request.POST, cities=cities, types=types)
    if form.data.get("website"):
        return redirect(lurl("/"))
    if not allow(request, "subscribe", limit=5):
        messages.error(request, _("Забагато спроб. Спробуйте пізніше."))
        return redirect(lurl("/"))
    if not form.is_valid():
        messages.error(request, _("Перевірте email і спробуйте ще раз."))
        return redirect(lurl("/") + "#subscribe")
    d = form.cleaned_data
    filters = {k: v for k, v in {"city": [int(c) for c in d["city"]], "type": d["type"]}.items() if v}
    if d["channel"] == "telegram":
        if not telegram.enabled():
            messages.error(request, _("Підписка в Telegram зʼявиться найближчим часом."))
            return redirect(lurl("/"))
        token = secrets.token_urlsafe(18)
        Subscription.objects.create(site=request.site, channel="telegram", address=f"pending-{token}", lang=lang(),
                                    filters=filters, digest=True, link_token=token,
                                    consent_source=f"form telegram {ip_hash(request)[:12]}")
        return redirect(telegram.deep_link(token))
    sub, _created = Subscription.objects.get_or_create(
        site=request.site, channel="email", address=d["email"].strip().lower(),
        defaults={"lang": lang(), "filters": filters, "consent_source": f"form {ip_hash(request)[:12]}"})
    _send_confirm(request, sub, filters, True)
    messages.success(request, _("Майже готово: відкрийте лист і підтвердіть підписку."))
    return redirect(lurl("/"))


def subscribe_confirm(request, token):
    data = read_confirm(token)
    sub = Subscription.objects.filter(pk=(data or {}).get("s"), site=request.site).first() if data else None
    if sub is None:
        messages.error(request, _("Посилання недійсне або застаріле."))
        return redirect(lurl("/"))
    sub.status, sub.lang = "active", lang()
    sub.consent_at = sub.consent_at or timezone.now()
    if data.get("r") is None:                      # a subscription form; a reminder keeps the existing choice
        sub.filters, sub.digest = data["f"], data["d"]
    sub.save()
    messages.success(request, _("Підписку підтверджено.") if data.get("r") is None
                     else _("Email підтверджено — нагадаємо за добу до події."))
    return redirect(lurl("/"))


@csrf_exempt
def unsubscribe(request, token):
    """GET shows a button (link scanners must not unsubscribe people); POST — incl. the mail client's one-click —
    stops the subscription at once."""
    pk = read_unsubscribe(token)
    sub = Subscription.objects.filter(pk=pk).first() if pk else None
    if sub is None:
        raise Http404
    if request.method == "POST":
        sub.status = "stopped"
        sub.save(update_fields=["status"])
        sub.reminders.filter(status="scheduled").update(status="cancelled")
        if request.headers.get("Content-Type", "").startswith("application/x-www-form-urlencoded") and \
                request.POST.get("List-Unsubscribe") == "One-Click":
            return HttpResponse("ok")
        return render(request, "subscriptions/unsubscribed.html", {"sub": sub})
    return render(request, "subscriptions/unsubscribe.html", {"sub": sub, "token": token})


@require_POST
def remind(request):
    form = RemindForm(request.POST)
    if form.data.get("website"):
        return redirect(lurl("/"))
    if not form.is_valid():
        messages.error(request, _("Перевірте email і спробуйте ще раз."))
        return redirect(request.META.get("HTTP_REFERER") or lurl("/"))
    o = (Occurrence.objects.filter(pk=form.cleaned_data["occurrence"], event__publications__site=request.site,
                                   event__publications__status="published").select_related("event").first())
    if o is None:
        raise Http404
    back = lurl(f"/events/{o.event.pk}-{o.event.slug}/")
    if not allow(request, "remind", limit=10):
        messages.error(request, _("Забагато спроб. Спробуйте пізніше."))
        return redirect(back)
    when = reminder_time(o)
    if when <= timezone.now() or o.status == "cancelled":
        messages.error(request, _("До події менше доби — нагадування вже не встигне."))
        return redirect(back)
    sub, _created = Subscription.objects.get_or_create(
        site=request.site, channel="email", address=form.cleaned_data["email"].strip().lower(),
        defaults={"lang": lang(), "digest": False, "consent_source": f"reminder {ip_hash(request)[:12]}"})
    r, _new = Reminder.objects.get_or_create(subscription=sub, occurrence=o, defaults={"send_at": when})
    if r.status == "cancelled":
        r.status, r.send_at = "scheduled", when
        r.save(update_fields=["status", "send_at"])
    if sub.status == "active":
        messages.success(request, _("Нагадаємо за добу до події."))
    else:
        _send_confirm(request, sub, sub.filters, sub.digest, reminder_id=r.pk)
        messages.success(request, _("Підтвердіть email у листі — і ми нагадаємо за добу до події."))
    return redirect(back)


@csrf_exempt
@require_POST
def telegram_webhook(request, secret):
    if not telegram.enabled() or not settings.TELEGRAM_WEBHOOK_SECRET or \
            not hmac.compare_digest(secret, settings.TELEGRAM_WEBHOOK_SECRET) or \
            not hmac.compare_digest(request.headers.get("X-Telegram-Bot-Api-Secret-Token", ""),
                                    settings.TELEGRAM_WEBHOOK_SECRET):
        return HttpResponseForbidden()
    try:
        msg = json.loads(request.body).get("message") or {}
    except ValueError:
        return JsonResponse({"ok": True})
    chat = str((msg.get("chat") or {}).get("id") or "")
    text = (msg.get("text") or "").strip()
    if not chat:
        return JsonResponse({"ok": True})
    if text.startswith("/start"):
        token = text.split(maxsplit=1)[1] if " " in text else ""
        sub = Subscription.objects.filter(channel="telegram", link_token=token).first() if token else None
        if sub is None:
            _reply(chat, "Щоб підписатися, натисніть «Підписатися» на сайті календаря.")
            return JsonResponse({"ok": True})
        existing = Subscription.objects.filter(site=sub.site, channel="telegram", address=chat).first()
        if existing and existing.pk != sub.pk:
            existing.filters, existing.lang, existing.status, existing.digest = sub.filters, sub.lang, "active", True
            existing.consent_at = existing.consent_at or timezone.now()
            existing.save()
            sub.delete()
        else:
            sub.address, sub.status, sub.link_token = chat, "active", ""
            sub.consent_at = timezone.now()
            sub.save()
        _reply(chat, "Готово! Щовівторка надсилатиму нові події за вашим вибором. Відписатися: /stop")
    elif text.startswith("/stop"):
        Subscription.objects.filter(channel="telegram", address=chat).update(status="stopped")
        _reply(chat, "Ви відписалися. Повернутися можна з сайту календаря.")
    return JsonResponse({"ok": True})


def _reply(chat: str, text: str) -> None:
    try:
        telegram.send_message(chat, text)
    except Exception:  # noqa: BLE001
        pass
