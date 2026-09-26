from django.contrib import admin

from .models import ChangeRequest


@admin.register(ChangeRequest)
class ChangeRequestAdmin(admin.ModelAdmin):
    list_display = ("created_at", "school", "requested_by_name", "summary", "status")
    list_filter = ("school", "status", "kind")
