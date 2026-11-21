from django.contrib import admin

from .models import Announcement, Delivery, Reminder, Subscription

admin.site.register(Subscription)
admin.site.register(Reminder)
admin.site.register(Announcement)
admin.site.register(Delivery)
