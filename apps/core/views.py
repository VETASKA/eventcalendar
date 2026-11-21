from django.db import connection
from django.http import HttpResponse, JsonResponse


def healthz(request):
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception as e:  # noqa: BLE001
        return JsonResponse({"ok": False, "db": str(e)[:200]}, status=503)
    return JsonResponse({"ok": True})


def home(request):
    # The public calendar arrives in stage 2; until then the root answers so the domain can be checked.
    return HttpResponse(f"<!doctype html><html lang='uk'><meta charset='utf-8'><title>{request.site}</title>"
                        f"<h1>{request.site}</h1><p>Календар подій — скоро.</p></html>")
