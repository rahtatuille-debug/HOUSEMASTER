from django.contrib import admin

from .models import Guardian, GuardianInvite


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ("display_name", "school", "user")
    list_filter = ("school",)
    filter_horizontal = ("students",)


@admin.register(GuardianInvite)
class GuardianInviteAdmin(admin.ModelAdmin):
    list_display = ("name", "email", "school", "invited_by", "created_at", "expires_at", "accepted_by")
    list_filter = ("school",)
    readonly_fields = ("token", "created_at", "accepted_at", "accepted_by")
    filter_horizontal = ("students",)
