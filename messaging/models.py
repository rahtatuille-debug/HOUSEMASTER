from django.conf import settings
from django.db import models

from students.models import School, Student


class Conversation(models.Model):
    """
    A 1:1 or small-group thread. Scoped to one school (both participant
    types — staff and guardians — are themselves single-school, so this
    just makes that constraint explicit and queryable). The optional
    `student` field tags what the conversation is about (e.g. "About:
    Amina Otieno") without restricting who can be a participant — that's
    enforced at the view/permission layer, not the model.
    """

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="conversations")
    student = models.ForeignKey(
        Student, on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations",
        help_text="Optional — which student this conversation is about, for context.",
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="ConversationParticipant", related_name="conversations"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="conversations_started"
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Conversation #{self.pk} ({self.school})"


class ConversationParticipant(models.Model):
    """
    Through-model so read status can be tracked per participant, per
    conversation — a bare ManyToManyField can't carry per-row state like
    last_read_at.
    """

    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participant_rows")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_rows")
    last_read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ("conversation", "user")


class Message(models.Model):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="messages_sent"
    )
    body = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"Message #{self.pk} in conversation #{self.conversation_id}"
