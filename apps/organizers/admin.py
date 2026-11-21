from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import Claim, EventGrant, Membership, Organization

for m in (Organization, Membership, Claim, EventGrant):
    admin.site.register(m, ModelAdmin)
