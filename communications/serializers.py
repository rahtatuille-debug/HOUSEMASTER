from rest_framework import serializers

from .models import Announcement


class AnnouncementSerializer(serializers.ModelSerializer):
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
