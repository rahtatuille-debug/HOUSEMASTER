from django.contrib import admin

from .models import Invite, PasswordResetToken, Profile


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "school", "role")
    list_filter = ("school", "role")


@admin.register(Invite)
class InviteAdmin(admin.ModelAdmin):
    list_display = ("school", "role", "name", "email", "invited_by", "created_at", "expires_at", "accepted_by")
    list_filter = ("school", "role")
    readonly_fields = ("token", "created_at", "accepted_at", "accepted_by")


@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display = ("user", "created_at", "expires_at", "used_at")
    readonly_fields = ("token", "created_at", "used_at")