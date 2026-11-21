from django.db import connection
from django.http import JsonResponse


def healthz(request):
    try:
        with connection.cursor() as c:
            c.execute("SELECT 1")
    except Exception as e:  # noqa: BLE001
        return JsonResponse({"ok": False, "db": str(e)[:200]}, status=503)
    return JsonResponse({"ok": True})

