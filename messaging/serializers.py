from django.contrib.auth.models import User
from rest_framework import serializers

from accounts.mixins import SchoolScopedRelatedFieldsMixin

from .models import Conversation, ConversationParticipant, Message
from .permissions import user_school


def _display_name(user):
    profile = getattr(user, "profile", None)
    if profile is not None:
        return profile.name, "staff"
    guardian = getattr(user, "guardian", None)
    if guardian is not None:
        return guardian.name, "guardian"
    return user.email, "unknown"


class MessageSerializer(serializers.ModelSerializer):
    sender_name = serializers.SerializerMethodField(read_only=True)
    sender_kind = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Message
        fields = ["id", "conversation", "sender", "sender_name", "sender_kind", "body", "created_at"]
        extra_kwargs = {
            "conversation": {"read_only": True},
            "sender": {"read_only": True},
            "created_at": {"read_only": True},
        }

    def get_sender_name(self, obj):
        if obj.sender is None:
            return None
        return _display_name(obj.sender)[0]

    def get_sender_kind(self, obj):
        if obj.sender is None:
            return None
        return _display_name(obj.sender)[1]

    def validate_body(self, value):
        body = value.strip()
        if not body:
            raise serializers.ValidationError("Message can't be empty.")
        return body


class ParticipantSerializer(serializers.Serializer):
    id = serializers.IntegerField(source="user_id")
    name = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()

    def get_name(self, row):
        return _display_name(row.user)[0]

    def get_kind(self, row):
        return _display_name(row.user)[1]


class ConversationSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    participants = serializers.SerializerMethodField(read_only=True)
    student_name = serializers.SerializerMethodField(read_only=True)
    last_message = serializers.SerializerMethodField(read_only=True)
    unread_count = serializers.SerializerMethodField(read_only=True)
    class_name = serializers.CharField(source="school_class.name", read_only=True, default=None)
    can_reply = serializers.SerializerMethodField(read_only=True)
    member_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id", "school", "kind", "school_class", "class_name", "student", "student_name",
            "participants", "member_count", "can_reply", "created_at", "last_message", "unread_count",
        ]
        extra_kwargs = {"school": {"read_only": True}, "kind": {"read_only": True},
                        "school_class": {"read_only": True}}

    def _viewer(self):
        request = self.context.get("request")
        return request.user if request else None

    def get_can_reply(self, obj):
        from .classes import can_post

        viewer = self._viewer()
        return bool(viewer) and can_post(obj, viewer)

    def get_member_count(self, obj):
        return obj.participant_rows.count()

    def get_participants(self, obj):
        rows = obj.participant_rows.select_related("user__profile", "user__guardian")
        viewer = self._viewer()
        if obj.kind == Conversation.Kind.CLASS_NOTICE and viewer is not None and not hasattr(viewer, "profile"):
            # Parents don't see who else received a one-way class notice.
            rows = rows.filter(user__profile__isnull=False)
        return ParticipantSerializer(rows, many=True).data

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}" if obj.student else None

    def get_last_message(self, obj):
        last = obj.messages.order_by("-created_at").first()
        if not last:
            return None
        return {"body": last.body, "created_at": last.created_at, "sender_id": last.sender_id}

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request:
            return 0
        row = obj.participant_rows.filter(user=request.user).first()
        if not row:
            return 0
        qs = obj.messages.exclude(sender=request.user)
        if row.last_read_at:
            qs = qs.filter(created_at__gt=row.last_read_at)
        return qs.count()


class ConversationCreateSerializer(serializers.Serializer):
    participant_ids = serializers.ListField(child=serializers.IntegerField(), min_length=1)
    student = serializers.IntegerField(required=False, allow_null=True)
    body = serializers.CharField(trim_whitespace=True)

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Message can't be empty.")
        return value

    # Refused people and children get the same answer as ones that don't
    # exist, so these checks can't be used to discover names or IDs
    # (messaging/contacts.py has the rules).
    PARTICIPANT_NOT_FOUND = "One or more participants could not be found."
    STUDENT_NOT_FOUND = "Student not found."

    def validate_participant_ids(self, value):
        from .contacts import messageable_users

        request = self.context["request"]
        wanted = set(value)
        if request.user.id in wanted:
            raise serializers.ValidationError("You don't need to add yourself as a participant.")
        allowed = set(messageable_users(request.user).filter(id__in=wanted).values_list("id", flat=True))
        if allowed != wanted:
            raise serializers.ValidationError(self.PARTICIPANT_NOT_FOUND)
        return value

    def validate_student(self, value):
        from .contacts import attachable_students

        if value is None:
            return value
        if not attachable_students(self.context["request"].user).filter(id=value).exists():
            raise serializers.ValidationError(self.STUDENT_NOT_FOUND)
        return value


class ClassMessageSerializer(serializers.Serializer):
    """Input for a teacher's message to every parent of one class."""

    school_class = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=[Conversation.Kind.CLASS_NOTICE, Conversation.Kind.CLASS_GROUP])
    body = serializers.CharField(trim_whitespace=True)

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Message can't be empty.")
        return value
