import os

os.environ.setdefault("DJANGO_DEBUG", "1")

import pytest
from django.core.management import call_command


@pytest.fixture
def ref(db):
    call_command("seed_reference", stdout=open(os.devnull, "w"))


@pytest.fixture
def harvey_token(ref):
    from apps.intake.models import EventSource
    src = EventSource.objects.create(code="harvey", name="Харві")
    return src.issue_token()


@pytest.fixture
def push(client, harvey_token):
    def _push(items, initial=False, token=None):
        r = client.post("/api/v1/intake/events", data={"schema": 1, "initial_load": initial, "items": items},
                        content_type="application/json", HTTP_AUTHORIZATION=f"Bearer {token or harvey_token}")
        return r
    return _push


def harvey_item(eid=1, **kw):
    d = {"external_id": str(eid), "url": f"https://event{eid}.com.ua/", "domain": f"event{eid}.com.ua",
         "name": f"Форум підприємців {eid}", "kind": "event", "kind_why": "є: дата", "country": "UA",
         "city": "Киев", "date": "2027-03-14", "date_text": "14 березня", "price_text": "500 грн",
         "registration_url": "https://tickets.example/ev", "organizer": {"name": "Агенція", "website": ""},
         "signals": {"ua_phone": True}, "updated_at": "2026-11-21T10:00:00Z", "removed": False}
    d.update(kw)
    return d
