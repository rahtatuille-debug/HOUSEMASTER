from django.contrib import admin

from .models import ActivityLog


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "school", "actor_name", "action", "summary")
    list_filter = ("school", "action")
    search_fields = ("summary", "actor_name")
    readonly_fields = [f.name for f in ActivityLog._meta.fields]
