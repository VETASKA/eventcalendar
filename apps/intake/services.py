"""Receiving a pushed record: store it once, normalise it, put it into the moderation queue."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.catalog import services as catalog

from .adapters import harvey
from .models import EventSource, IntakeItem

ADAPTERS = {"harvey": harvey.normalize}
VOLATILE = {"updated_at", "sent_at", "scanned_at"}   # changes that alone do not mean «the event changed»


class IntakeError(ValueError):
    pass


def payload_hash(p: dict) -> str:
    stable = {k: v for k, v in p.items() if k not in VOLATILE}
    return hashlib.sha256(json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


def _parse_dt(v) -> datetime | None:
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if timezone.is_aware(dt) else timezone.make_aware(dt, timezone.utc)


def receive(source: EventSource, raw: dict, *, schema: int = 1, initial_load: bool = False) -> dict:
    if not isinstance(raw, dict):
        raise IntakeError("item must be an object")
    ext = str(raw.get("external_id") or "").strip()
    if not ext or len(ext) > 200:
        raise IntakeError("external_id is required")
    h = payload_hash(raw)

    with transaction.atomic():
        item = IntakeItem.objects.select_for_update().filter(source=source, external_id=ext).first()
        created = False
        if item is None:
            try:
                with transaction.atomic():
                    item = IntakeItem.objects.create(source=source, external_id=ext, payload=raw, payload_hash=h,
                                                     schema_version=schema, initial_load=initial_load)
                    created = True
            except IntegrityError:            # a parallel request created it first: wait for it, then go on
                item = IntakeItem.objects.select_for_update().get(source=source, external_id=ext)
        if not created and item.payload_hash == h and item.status != "queued":
            return {"external_id": ext, "result": "unchanged", "status": item.status,
                    "event_id": item.event_id}
        if not created:
            item.payload, item.payload_hash, item.schema_version = raw, h, schema
        item.url = (raw.get("url") or "")[:1000]
        item.source_updated_at = _parse_dt(raw.get("updated_at"))
        item.status = "processing"
        item.attempts += 1
        item.save()
        process(item)
    return {"external_id": ext, "result": "created" if created else "updated", "status": item.status,
            "event_id": item.event_id}


def process(item: IntakeItem) -> None:
    """Normalise and apply. Called inside the receive() transaction, or by a moderator's «повторити»."""
    normalize = ADAPTERS.get(item.source.code, harvey.normalize)
    n = normalize(item.payload)
    item.normalized = n
    item.normalized_url = n["normalized_url"]
    item.status = n["status"]
    item.reason = n["reason"]
    item.removed_in_source = n["removed"]
    catalog.apply_intake(item, n)
    item.processed_at = timezone.now()
    item.save()
