from django.contrib import admin

from .models import Conversation, ConversationParticipant, Message


class ParticipantInline(admin.TabularInline):
    model = ConversationParticipant
    extra = 0
    readonly_fields = ("last_read_at",)


class MessageInline(admin.TabularInline):
    model = Message
    extra = 0
    readonly_fields = ("sender", "body", "created_at")


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ("id", "school", "student", "created_by", "created_at")
    list_filter = ("school",)
    inlines = [ParticipantInline, MessageInline]
