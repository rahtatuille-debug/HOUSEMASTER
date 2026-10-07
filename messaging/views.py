from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from django.db.models import Q
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError
from rest_framework.response import Response

from accounts.scoping import is_admin
from activity.services import log_activity
from housemaster.pagination import LongListPagination
from students.models import SchoolClass

from .classes import can_post, guardian_class_ids, start_class_conversation, sync_class_participants
from .models import Conversation, ConversationParticipant, Message
from .contacts import children_by_parent, contact_list
from .permissions import CanMessage, user_school
from .throttles import ClassMessageThrottle
from .serializers import (
    ClassMessageSerializer,
    ConversationCreateSerializer,
    ConversationSerializer,
    MessageSerializer,
    _display_name,
    with_list_fields,
)


class ConversationViewSet(viewsets.ModelViewSet):
    """
    Conversations are only ever visible to their own participants — not
    school-wide, even for admins. This is a deliberate privacy choice for
    a direct-messaging feature: it isn't an announcement board. An
    oversight/audit view for admins could be added later as a distinct,
    explicitly-labelled capability, but isn't part of this feature.
    """

    serializer_class = ConversationSerializer
    permission_classes = [CanMessage]
    http_method_names = ["get", "post", "head", "options"]
    # A page at a time, newest first (B-1). The frontend already shipped
    # follows the pages.
    pagination_class = LongListPagination

    def get_queryset(self):
        queryset = with_list_fields(
            Conversation.objects.filter(participants=self.request.user).distinct(), self.request.user
        ).order_by("-created_at", "-id")
        guardian = getattr(self.request.user, "guardian", None)
        if guardian is not None:
            # A parent who has left a class loses its class conversations at
            # once, even before the next message updates the member list.
            queryset = queryset.filter(
                Q(kind=Conversation.Kind.DIRECT) | Q(school_class_id__in=guardian_class_ids(guardian))
            )
        return queryset

    def get_object(self):
        conversation = super().get_object()
        if not conversation.participant_rows.filter(user=self.request.user).exists():
            raise NotFound("Conversation not found.")
        return conversation

    def create(self, request, *args, **kwargs):
        serializer = ConversationCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        conversation = Conversation.objects.create(
            school=user_school(request.user),
            student_id=data.get("student"),
            created_by=request.user,
        )
        participant_ids = set(data["participant_ids"]) | {request.user.id}
        now = timezone.now()
        for user_id in participant_ids:
            ConversationParticipant.objects.create(
                conversation=conversation, user_id=user_id,
                last_read_at=now if user_id == request.user.id else None,
            )
        Message.objects.create(conversation=conversation, sender=request.user, body=data["body"])

        return Response(
            ConversationSerializer(conversation, context={"request": request}).data, status=201
        )

    @action(detail=True, methods=["get", "post"])
    def messages(self, request, pk=None):
        conversation = self.get_object()

        if request.method == "GET":
            # Oldest first, a page at a time (F-14).
            messages = conversation.messages.select_related(
                "sender__profile", "sender__guardian").order_by("created_at", "id")
            paginator = LongListPagination()
            page = paginator.paginate_queryset(messages, request, view=self)
            return paginator.get_paginated_response(MessageSerializer(page, many=True).data)

        if not can_post(conversation, request.user):
            raise PermissionDenied("Replies are turned off for this class notice. Message the teacher directly instead.")
        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sync_class_participants(conversation)
        message = Message.objects.create(
            conversation=conversation, sender=request.user, body=serializer.validated_data["body"]
        )
        return Response(MessageSerializer(message).data, status=201)

    @action(detail=False, methods=["post"], url_path="class", throttle_classes=[ClassMessageThrottle])
    def class_message(self, request):
        """
        Message every parent of one class at once, as a one-way notice
        (kind=class_notice) or a discussion everyone can reply to
        (kind=class_group). Teachers can only message classes they teach;
        admins can message any class at their school.
        """
        if not hasattr(request.user, "profile"):
            raise PermissionDenied("Only staff can message a whole class.")
        serializer = ClassMessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            school_class = SchoolClass.objects.select_related("year_group").get(
                pk=data["school_class"], year_group__school=request.user.profile.school
            )
        except SchoolClass.DoesNotExist:
            raise ValidationError({"school_class": "Class not found."})
        if not is_admin(request.user) and not request.user.profile.assignments.filter(
            school_class=school_class
        ).exists():
            raise PermissionDenied("You can only message classes you teach.")

        from .classes import class_parent_users

        if not class_parent_users(school_class).exists():
            raise ValidationError("No parents in this class have an account yet.")
        conversation = start_class_conversation(
            sender=request.user, school_class=school_class, kind=data["kind"], body=data["body"],
        )
        label = "a notice" if data["kind"] == Conversation.Kind.CLASS_NOTICE else "a discussion"
        log_activity(
            school=conversation.school, actor=request.user, action="class_message.created",
            target=conversation,
            summary=f"Started {label} with {conversation.participant_rows.count() - 1} parents of {school_class.name}",
        )
        return Response(ConversationSerializer(conversation, context={"request": request}).data, status=201)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        conversation = self.get_object()
        ConversationParticipant.objects.filter(
            conversation=conversation, user=request.user
        ).update(last_read_at=timezone.now())
        return Response({"detail": "Marked as read."})

    @action(detail=False, methods=["get"])
    def contacts(self, request):
        """
        Who the caller is offered in the "new message" picker: the other
        identity type at their own school, narrowed by the rules in
        messaging/contacts.py (parents see their children's teachers and the
        admins; teachers see parents of their own pupils).
        """
        users = list(contact_list(request.user))
        rows = [{"id": u.id, "name": _display_name(u)[0], "kind": _display_name(u)[1]} for u in users]
        # Staff also get each parent's children, so a message can only be
        # about one of them.
        if getattr(request.user, "guardian", None) is None and getattr(request.user, "profile", None) is not None:
            children = children_by_parent(request.user, users)
            for row in rows:
                row["children"] = children.get(row["id"], [])
        return Response(rows)
