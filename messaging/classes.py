"""Membership rules for class notices and class discussions."""
from django.contrib.auth.models import User
from django.utils import timezone

from .models import Conversation, ConversationParticipant


def class_parent_users(school_class):
    """Active parents with an active child in this class."""
    return User.objects.filter(
        is_active=True,
        guardian__students__school_class=school_class,
        guardian__students__is_active=True,
    ).distinct()


def guardian_class_ids(guardian):
    """The classes a parent currently belongs to, through their active children."""
    return guardian.students.filter(is_active=True, school_class__isnull=False).values_list(
        "school_class_id", flat=True
    )


def sync_class_participants(conversation):
    """
    Bring a class conversation's parent list in line with the class:
    add parents who have joined, remove parents who have left. Staff
    participants (the teacher who started it) are never removed.
    """
    if not conversation.is_class or conversation.school_class_id is None:
        return
    current = set(class_parent_users(conversation.school_class).values_list("id", flat=True))
    existing_parents = set(
        conversation.participant_rows.filter(user__guardian__isnull=False).values_list("user_id", flat=True)
    )
    for user_id in current - existing_parents:
        ConversationParticipant.objects.create(conversation=conversation, user_id=user_id)
    conversation.participant_rows.filter(user_id__in=existing_parents - current).delete()


def can_post(conversation, user):
    """Anyone in a conversation can post, except parents in a one-way class notice."""
    if conversation.kind == Conversation.Kind.CLASS_NOTICE:
        return hasattr(user, "profile")
    return True


def start_class_conversation(*, sender, school_class, kind, body):
    conversation = Conversation.objects.create(
        school=school_class.year_group.school, kind=kind, school_class=school_class, created_by=sender,
    )
    ConversationParticipant.objects.create(conversation=conversation, user=sender, last_read_at=timezone.now())
    sync_class_participants(conversation)
    conversation.messages.create(sender=sender, body=body)
    return conversation
