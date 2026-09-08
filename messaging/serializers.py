from django.contrib.auth.models import User
from rest_framework import serializers

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


class ConversationSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField(read_only=True)
    student_name = serializers.SerializerMethodField(read_only=True)
    last_message = serializers.SerializerMethodField(read_only=True)
    unread_count = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Conversation
        fields = [
            "id", "school", "student", "student_name", "participants",
            "created_at", "last_message", "unread_count",
        ]
        extra_kwargs = {"school": {"read_only": True}}

    def get_participants(self, obj):
        rows = obj.participant_rows.select_related("user__profile", "user__guardian")
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

    def validate_participant_ids(self, value):
        request = self.context["request"]
        caller_school = user_school(request.user)
        users = User.objects.filter(id__in=value)
        if users.count() != len(set(value)):
            raise serializers.ValidationError("One or more participants could not be found.")
        for user in users:
            if user_school(user) != caller_school:
                raise serializers.ValidationError("All participants must be at your own school.")
            if user.id == request.user.id:
                raise serializers.ValidationError("You don't need to add yourself as a participant.")
        return value

    def validate_student(self, value):
        if value is None:
            return value
        from students.models import Student

        request = self.context["request"]
        try:
            student = Student.objects.get(id=value, school=user_school(request.user))
        except Student.DoesNotExist:
            raise serializers.ValidationError("Student not found at your school.")
        return student.id
