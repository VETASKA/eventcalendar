from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Announcement, Delivery, Reminder, Subscription

for m in (Subscription, Reminder, Announcement, Delivery):
    admin.site.register(m, ModelAdmin)
