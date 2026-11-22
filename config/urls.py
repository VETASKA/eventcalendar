from django.contrib import admin
from django.urls import path, re_path

from apps.core import views as core
from apps.intake import views as intake
from apps.public import cabinet
from apps.public import views as public

admin.site.site_header = "EventCalendar — модерация"
admin.site.site_title = "EventCalendar"

urlpatterns = [
    path("healthz", core.healthz),
    path("api/v1/intake/events", intake.intake_events),
    path("admin/", admin.site.urls),
    path("api/v1/events", public.events_api),
    path("api/v1/search", public.search_api),
    path("events/<int:pk>/report/", cabinet.report_error),
    path("events/<int:pk>/claim/", cabinet.claim_view),
    re_path(r"^events/(?P<pk>\d+)(?:-(?P<slug>[^/]*))?/$", public.event_page, name="event"),
    path("suggest/", cabinet.suggest_view),
    path("cabinet/", cabinet.cabinet_view),
    path("cabinet/login/", cabinet.login_view),
    path("cabinet/register/", cabinet.register_view),
    path("cabinet/logout/", cabinet.logout_view),
    path("", public.calendar_page),
]
