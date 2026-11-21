from django.contrib import admin

from .models import Claim, EventGrant, Membership, Organization

admin.site.register(Organization)
admin.site.register(Membership)
admin.site.register(Claim)
admin.site.register(EventGrant)
