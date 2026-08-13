from django.contrib import admin

from .models import Profile, Invite


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "role")
    list_filter = ("school", "role")


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("school", "role", "email", "invited_by", "created_at", "expires_at", "accepted_by")
    list_filter = ("school", "role")
    readonly_fields = ("token", "created_at", "accepted_at", "accepted_by")