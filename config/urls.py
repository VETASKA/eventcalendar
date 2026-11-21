from django.contrib import admin
from django.urls import path

from apps.core import views as core
from apps.intake import views as intake

admin.site.site_header = "EventCalendar — модерація"
admin.site.site_title = "EventCalendar"

urlpatterns = [
    path("healthz", core.healthz),
    path("api/v1/intake/events", intake.intake_events),
    path("admin/", admin.site.urls),
    path("", core.home),
]
