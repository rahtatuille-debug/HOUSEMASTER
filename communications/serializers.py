from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin

from activity.services import display_name

from .models import AlertRecipient, Announcement, UrgentAlert


class AnnouncementSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField(read_only=True)
    created_by_role = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Announcement
        fields = [
            "id",
            "school",
            "title",
            "body",
            "audience",
            "year_group",
            "school_class",
            "status",
            "created_by",
            "created_by_name",
            "created_by_role",
            "created_at",
            "published_at",
            "archived_at",
        ]
        read_only_fields = [
            "school",
            "status",
            "created_by",
            "created_at",
            "published_at",
            "archived_at",
        ]

    def get_created_by_name(self, obj):
        profile = getattr(obj.created_by, "profile", None) if obj.created_by else None
        if profile is None:
            return None
        return profile.name

    def get_created_by_role(self, obj):
        profile = getattr(obj.created_by, "profile", None) if obj.created_by else None
        if profile is None:
            return None
        return profile.get_role_display()

    def validate(self, attrs):
        audience = attrs.get("audience", getattr(self.instance, "audience", None))
        year_group = attrs.get("year_group", getattr(self.instance, "year_group", None))
        school_class = attrs.get("school_class", getattr(self.instance, "school_class", None))

        if audience == Announcement.Audience.YEAR_GROUP:
            if year_group is None or school_class is not None:
                raise serializers.ValidationError(
                    "A year-group announcement needs a year_group and cannot include school_class."
                )
        elif audience == Announcement.Audience.SCHOOL_CLASS:
            if school_class is None or year_group is not None:
                raise serializers.ValidationError(
                    "A class announcement needs a school_class and cannot include year_group."
                )
        elif year_group is not None or school_class is not None:
            raise serializers.ValidationError(
                "All-staff and all-parent announcements cannot include a class or year_group."
            )
        return attrs


class GenerateAnnouncementTextSerializer(serializers.Serializer):
    """A short staff brief used to generate an editable announcement draft."""

    summary = serializers.CharField(min_length=10, max_length=2000, trim_whitespace=True)
    audience = serializers.ChoiceField(
        choices=Announcement.Audience.choices, required=False, default=Announcement.Audience.ALL_STAFF
    )
    year_group = serializers.IntegerField(required=False, allow_null=True)
    school_class = serializers.IntegerField(required=False, allow_null=True)


class UrgentAlertSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    created_by_name = serializers.SerializerMethodField()
    audience_label = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(read_only=True)
    my_acknowledged_at = serializers.SerializerMethodField()
    recipient_count = serializers.SerializerMethodField()
    acknowledged_count = serializers.SerializerMethodField()

    class Meta:
        model = UrgentAlert
        fields = [
            "id", "title", "body", "audience", "audience_label", "year_group", "school_class",
            "created_by", "created_by_name", "created_at", "ended_at", "is_active",
            "my_acknowledged_at", "recipient_count", "acknowledged_count",
        ]
        read_only_fields = ["created_by", "created_at", "ended_at"]

    def get_created_by_name(self, obj):
        return display_name(obj.created_by) if obj.created_by else None

    def get_audience_label(self, obj):
        target = obj.school_class or obj.year_group
        label = obj.get_audience_display()
        return f"{label}: {target.name}" if target else label

    def _viewer(self):
        request = self.context.get("request")
        return request.user if request else None

    def _can_see_counts(self, obj):
        viewer = self._viewer()
        if viewer is None:
            return False
        profile = getattr(viewer, "profile", None)
        return obj.created_by_id == viewer.id or (profile is not None and profile.is_admin)

    def get_my_acknowledged_at(self, obj):
        viewer = self._viewer()
        row = obj.recipients.filter(user=viewer).first() if viewer else None
        return row.acknowledged_at if row else None

    def get_recipient_count(self, obj):
        return obj.recipients.count() if self._can_see_counts(obj) else None

    def get_acknowledged_count(self, obj):
        return obj.recipients.filter(acknowledged_at__isnull=False).count() if self._can_see_counts(obj) else None

    def validate(self, attrs):
        audience = attrs.get("audience")
        if audience == UrgentAlert.Audience.YEAR_GROUP and not attrs.get("year_group"):
            raise serializers.ValidationError({"year_group": "Choose a year group."})
        if audience == UrgentAlert.Audience.SCHOOL_CLASS and not attrs.get("school_class"):
            raise serializers.ValidationError({"school_class": "Choose a class."})
        if audience != UrgentAlert.Audience.YEAR_GROUP:
            attrs["year_group"] = None
        if audience != UrgentAlert.Audience.SCHOOL_CLASS:
            attrs["school_class"] = None
        for field in ("title", "body"):
            if not attrs.get(field, "").strip():
                raise serializers.ValidationError({field: "This can't be empty."})
        return attrs


class AlertRecipientSerializer(serializers.ModelSerializer):
    """Who an alert went to and whether they've seen it, for the sender and admins."""

    name = serializers.SerializerMethodField()
    kind = serializers.SerializerMethodField()
    children = serializers.SerializerMethodField()

    class Meta:
        model = AlertRecipient
        fields = ["id", "user", "name", "kind", "children", "acknowledged_at"]

    def get_name(self, obj):
        return display_name(obj.user)

    def get_kind(self, obj):
        return "staff" if hasattr(obj.user, "profile") else "parent"

    def get_children(self, obj):
        guardian = getattr(obj.user, "guardian", None)
        if guardian is None:
            return []
        return [f"{s.first_name} {s.last_name}" for s in guardian.students.all()]
