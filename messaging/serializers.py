from django.contrib.auth.models import User
from django.db.models import Case, Count, IntegerField, OuterRef, Prefetch, Subquery, Value, When
from django.db.models.functions import Coalesce
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


def _count(queryset):
    return Coalesce(Subquery(queryset.order_by().values("conversation").annotate(n=Count("id")).values("n")[:1],
                             output_field=IntegerField()), Value(0))


def with_list_fields(queryset, viewer):
    """
    Adds what ConversationSerializer shows for each row (members, the last
    message, the viewer's unread count and the participants' names) in a
    fixed number of queries, however many conversations there are (B-1).
    """
    messages = Message.objects.filter(conversation=OuterRef("pk"))
    last = messages.order_by("-created_at", "-id")
    unread = messages.exclude(sender=viewer)
    read_at = ConversationParticipant.objects.filter(conversation=OuterRef("pk"), user=viewer).values("last_read_at")
    return queryset.select_related("student", "school_class").annotate(
        member_total=_count(ConversationParticipant.objects.filter(conversation=OuterRef("pk"))),
        viewer_read_at=Subquery(read_at[:1]),
        last_body=Subquery(last.values("body")[:1]),
        last_at=Subquery(last.values("created_at")[:1]),
        last_sender=Subquery(last.values("sender_id")[:1]),
    ).annotate(
        unread_total=Case(
            When(viewer_read_at__isnull=True, then=_count(unread)),
            default=_count(unread.filter(created_at__gt=OuterRef("viewer_read_at"))),
            output_field=IntegerField(),
        ),
    ).prefetch_related(Prefetch(
        "participant_rows",
        queryset=ConversationParticipant.objects.select_related("user__profile", "user__guardian").order_by("id"),
    ))


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

    # Lists come from with_list_fields() (annotated, participants
    # prefetched); a single conversation that wasn't loaded that way (the
    # one just created) is worked out with its own queries.

    def get_member_count(self, obj):
        total = getattr(obj, "member_total", None)
        return total if total is not None else obj.participant_rows.count()

    def get_participants(self, obj):
        if "participant_rows" in getattr(obj, "_prefetched_objects_cache", {}):
            rows = list(obj.participant_rows.all())
        else:
            rows = list(obj.participant_rows.select_related("user__profile", "user__guardian").order_by("id"))
        viewer = self._viewer()
        if obj.kind == Conversation.Kind.CLASS_NOTICE and viewer is not None and not hasattr(viewer, "profile"):
            # Parents don't see who else received a one-way class notice.
            rows = [row for row in rows if hasattr(row.user, "profile")]
        return ParticipantSerializer(rows, many=True).data

    def get_student_name(self, obj):
        return f"{obj.student.first_name} {obj.student.last_name}" if obj.student else None

    def get_last_message(self, obj):
        if hasattr(obj, "last_at"):
            if obj.last_at is None:
                return None
            return {"body": obj.last_body, "created_at": obj.last_at, "sender_id": obj.last_sender}
        last = obj.messages.order_by("-created_at", "-id").first()
        if not last:
            return None
        return {"body": last.body, "created_at": last.created_at, "sender_id": last.sender_id}

    def get_unread_count(self, obj):
        request = self.context.get("request")
        if not request:
            return 0
        if hasattr(obj, "unread_total"):
            return obj.unread_total
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
        from .contacts import messageable_users, parents_share_a_child

        request = self.context["request"]
        wanted = set(value)
        if request.user.id in wanted:
            raise serializers.ValidationError("You don't need to add yourself as a participant.")
        allowed = set(messageable_users(request.user).filter(id__in=wanted).values_list("id", flat=True))
        # Parents of different children can't share a direct conversation;
        # refused with the same answer, so it doesn't reveal who is related.
        if allowed != wanted or not parents_share_a_child(wanted | {request.user.id}):
            raise serializers.ValidationError(self.PARTICIPANT_NOT_FOUND)
        return value

    def validate_student(self, value):
        from .contacts import attachable_students

        if value is None:
            return value
        if not attachable_students(self.context["request"].user).filter(id=value).exists():
            raise serializers.ValidationError(self.STUDENT_NOT_FOUND)
        return value

    def validate(self, attrs):
        from .contacts import is_every_parents_child

        # A conversation with parents can only be about one of their own
        # children, never another family's (same answer as "not found").
        student = attrs.get("student")
        if student is not None and not is_every_parents_child(student, attrs["participant_ids"]):
            raise serializers.ValidationError({"student": [self.STUDENT_NOT_FOUND]})
        return attrs


class ClassMessageSerializer(serializers.Serializer):
    """Input for a teacher's message to every parent of one class."""

    school_class = serializers.IntegerField()
    kind = serializers.ChoiceField(choices=[Conversation.Kind.CLASS_NOTICE, Conversation.Kind.CLASS_GROUP])
    body = serializers.CharField(trim_whitespace=True)

    def validate_body(self, value):
        if not value.strip():
            raise serializers.ValidationError("Message can't be empty.")
        return value
