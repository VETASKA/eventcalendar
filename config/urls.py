from django.contrib import admin
from django.urls import path, re_path

from apps.core import views as core
from apps.intake import views as intake
from apps.public import views as public

admin.site.site_header = "EventCalendar — модерация"
admin.site.site_title = "EventCalendar"

urlpatterns = [
    path("healthz", core.healthz),
    path("api/v1/intake/events", intake.intake_events),
    path("admin/", admin.site.urls),
    path("api/v1/events", public.events_api),
    re_path(r"^events/(?P<pk>\d+)(?:-(?P<slug>[^/]*))?/$", public.event_page, name="event"),
    path("", public.calendar_page),
]
