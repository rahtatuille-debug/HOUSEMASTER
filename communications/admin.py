from django.contrib import admin

from .models import Announcement, UrgentAlert


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = ("title", "school", "audience", "status", "published_at", "created_by")
    list_filter = ("school", "audience", "status")
    search_fields = ("title", "body")
    readonly_fields = ("created_at", "published_at", "archived_at")


@admin.register(UrgentAlert)
class UrgentAlertAdmin(admin.ModelAdmin):
    list_display = ("created_at", "school", "title", "audience", "ended_at")
    list_filter = ("school", "audience")
