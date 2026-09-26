from django.conf import settings
from django.db import models

from students.models import School, SchoolClass, Student


class Conversation(models.Model):
    """
    Three kinds:

    - direct: the original 1:1 or small-group thread between staff and
      parents.
    - class_notice: a teacher's one-way message to every parent of one
      class. Parents can read it but not reply, and don't see who else
      received it.
    - class_group: a discussion with every parent of one class. Everyone
      in it can post and sees who else is in it.

    Class conversations keep their parent list in step with the class (see
    messaging.classes): parents who join the class are added when the next
    message is sent, and parents who leave it lose access straight away.

    A 1:1 or small-group thread. Scoped to one school (both participant
    types — staff and guardians — are themselves single-school, so this
    just makes that constraint explicit and queryable). The optional
    `student` field tags what the conversation is about (e.g. "About:
    Amina Otieno") without restricting who can be a participant — that's
    enforced at the view/permission layer, not the model.
    """

    class Kind(models.TextChoices):
        DIRECT = "direct", "Direct message"
        CLASS_NOTICE = "class_notice", "Class notice"
        CLASS_GROUP = "class_group", "Class discussion"

    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name="conversations")
    kind = models.CharField(max_length=20, choices=Kind.choices, default=Kind.DIRECT)
    school_class = models.ForeignKey(
        SchoolClass, on_delete=models.SET_NULL, null=True, blank=True, related_name="conversations",
        help_text="For class notices and discussions: the class whose parents are in it.",
    )
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

    @property
    def is_class(self):
        return self.kind in (self.Kind.CLASS_NOTICE, self.Kind.CLASS_GROUP)

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
