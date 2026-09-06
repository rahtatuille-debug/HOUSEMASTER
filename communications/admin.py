from django.contrib import admin

from .models import Announcement


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "school", "audience", "status", "published_at", "created_by")
    list_filter = ("school", "audience", "status")
    search_fields = ("title", "body")
    readonly_fields = ("created_at", "published_at", "archived_at")
