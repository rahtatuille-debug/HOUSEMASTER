from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, PermissionDenied
from rest_framework.response import Response

from .models import Conversation, ConversationParticipant, Message
from .permissions import CanMessage, user_school
from .serializers import ConversationCreateSerializer, ConversationSerializer, MessageSerializer, _display_name


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

    def get_queryset(self):
        return Conversation.objects.filter(participants=self.request.user).distinct()

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
            messages = conversation.messages.select_related("sender")
            return Response(MessageSerializer(messages, many=True).data)

        serializer = MessageSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = Message.objects.create(
            conversation=conversation, sender=request.user, body=serializer.validated_data["body"]
        )
        return Response(MessageSerializer(message).data, status=201)

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
        Who the caller is allowed to start a new conversation with: the
        other identity type at their own school (staff see guardians,
        guardians see staff) — matches the "teacher <-> parent" framing
        this feature was built for, rather than allowing staff-to-staff
        DMs here (nothing stops that at the model level if it's wanted
        later, this endpoint just doesn't surface it as a default contact
        list yet).
        """
        school = user_school(request.user)
        if hasattr(request.user, "guardian"):
            users = User.objects.filter(profile__school=school).exclude(id=request.user.id)
        else:
            users = User.objects.filter(guardian__school=school).exclude(id=request.user.id)
        return Response([
            {"id": u.id, "name": _display_name(u)[0], "kind": _display_name(u)[1]} for u in users
        ])
