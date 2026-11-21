"""POST /api/v1/intake/events — the push endpoint for Harvey (contract: docs/intake-api.md)."""
import hmac
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import EventSource
from .services import IntakeError, receive

logger = logging.getLogger(__name__)
SUPPORTED_SCHEMAS = {1}


def _source_for(request) -> EventSource | None:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    digest = EventSource.hash_token(auth[7:].strip())
    for src in EventSource.objects.filter(is_active=True).exclude(token_hash=""):
        if hmac.compare_digest(src.token_hash, digest):
            return src
    return None


@csrf_exempt
@require_POST
def intake_events(request):
    source = _source_for(request)
    if source is None:
        return JsonResponse({"error": "unauthorized"}, status=401)
    try:
        body = json.loads(request.body or b"{}")
    except ValueError:
        return JsonResponse({"error": "invalid json"}, status=400)
    schema = body.get("schema")
    if schema not in SUPPORTED_SCHEMAS:
        return JsonResponse({"error": f"unsupported schema {schema!r}", "supported": sorted(SUPPORTED_SCHEMAS)},
                            status=400)
    items = body.get("items")
    if not isinstance(items, list) or not items:
        return JsonResponse({"error": "items must be a non-empty list"}, status=400)
    if len(items) > settings.INTAKE_MAX_BATCH:
        return JsonResponse({"error": f"at most {settings.INTAKE_MAX_BATCH} items per request"}, status=413)

    initial = bool(body.get("initial_load"))
    results = []
    for raw in items:
        try:
            results.append(receive(source, raw, schema=schema, initial_load=initial))
        except IntakeError as e:
            results.append({"external_id": str((raw or {}).get("external_id", "")), "result": "error",
                            "error": str(e)})
        except Exception:  # one bad item must not lose the batch
            logger.exception("intake item failed")
            results.append({"external_id": str((raw or {}).get("external_id", "")), "result": "error",
                            "error": "internal error"})
    EventSource.objects.filter(pk=source.pk).update(last_seen_at=timezone.now())
    return JsonResponse({"schema": schema, "results": results})
