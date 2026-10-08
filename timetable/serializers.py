from rest_framework import serializers

from accounts.models import Profile
from gradebook.models import Subject
from students.models import SchoolClass

from . import services
from .models import Lesson, Period, Room


class PeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Period
        fields = ["id", "name", "start_time", "end_time", "is_break"]

    def validate(self, data):
        start = data.get("start_time", getattr(self.instance, "start_time", None))
        end = data.get("end_time", getattr(self.instance, "end_time", None))
        if start and end and end <= start:
            raise serializers.ValidationError({"end_time": ["The period must end after it starts."]})
        school = self.context["request"].user.profile.school
        overlapping = Period.objects.filter(school=school, start_time__lt=end, end_time__gt=start)
        if self.instance:
            overlapping = overlapping.exclude(pk=self.instance.pk)
        if start and end and overlapping.exists():
            raise serializers.ValidationError(
                {"start_time": [f"It overlaps {overlapping.first().name}. Periods can't overlap."]})
        if data.get("is_break") and self.instance and self.instance.lessons.exists():
            raise serializers.ValidationError({"is_break": ["Move its lessons first: a break can't hold lessons."]})
        return data


class RoomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Room
        fields = ["id", "name"]

    def validate_name(self, value):
        value = value.strip()
        school = self.context["request"].user.profile.school
        same = Room.objects.filter(school=school, name__iexact=value)
        if self.instance:
            same = same.exclude(pk=self.instance.pk)
        if not value or same.exists():
            raise serializers.ValidationError("Give the room a name no other room has.")
        return value


class LessonSerializer(serializers.ModelSerializer):
    """Placing a lesson. The teacher defaults to whoever teaches the subject to the class (Staff page)."""

    class Meta:
        model = Lesson
        fields = ["id", "school_class", "subject", "title", "teacher", "room", "day", "period"]

    def get_fields(self):
        fields = super().get_fields()
        school = self.context["request"].user.profile.school
        fields["school_class"].queryset = SchoolClass.objects.filter(year_group__school=school)
        fields["subject"].queryset = Subject.objects.filter(school=school)
        fields["teacher"].queryset = Profile.objects.filter(school=school, user__is_active=True)
        fields["room"].queryset = Room.objects.filter(school=school)
        fields["period"].queryset = Period.objects.filter(school=school)
        return fields

    def validate(self, data):
        school = self.context["request"].user.profile.school
        merged = {f: getattr(self.instance, f) for f in self.Meta.fields if f != "id"} if self.instance else {}
        merged.update(data)
        if not merged.get("subject") and not (merged.get("title") or "").strip():
            raise serializers.ValidationError({"subject": ["Choose a subject, or give the lesson a title."]})
        if merged.get("day") not in services.school_days(school):
            raise serializers.ValidationError({"day": ["The school doesn't teach on that day."]})
        if "teacher" not in data and not self.instance and merged.get("subject"):
            data["teacher"] = merged["teacher"] = services.default_teacher(merged["school_class"], merged["subject"])
        lesson = Lesson(pk=getattr(self.instance, "pk", None), school=school, **{
            k: v for k, v in merged.items() if k in ("school_class", "subject", "title", "teacher", "room", "day",
                                                     "period")})
        problems = services.clashes(lesson)
        if problems:
            raise serializers.ValidationError({"non_field_errors": problems})
        return data

    def to_representation(self, instance):
        return services.lesson_row(instance)


class StaffAbsenceSerializer(serializers.ModelSerializer):
    teacher_name = serializers.CharField(source="teacher.name", read_only=True)
    reason_label = serializers.CharField(source="get_reason_display", read_only=True)

    class Meta:
        from .models import StaffAbsence

        model = StaffAbsence
        fields = ["id", "teacher", "teacher_name", "start_date", "end_date", "periods", "reason", "reason_label",
                  "note", "recorded_by_name", "created_at"]
        read_only_fields = ["recorded_by_name", "created_at"]
        extra_kwargs = {"periods": {"required": False}}

    def get_fields(self):
        from accounts.models import Profile

        from .models import Period

        fields = super().get_fields()
        request = self.context.get("request")
        school = request.user.profile.school if request else None
        fields["teacher"].queryset = Profile.objects.filter(school=school).exclude(role=Profile.Role.GOVERNOR)
        fields["periods"].child_relation.queryset = Period.objects.filter(school=school, is_break=False)
        return fields

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError({"end_date": ["The last day can't be before the first."]})
        if (attrs["end_date"] - attrs["start_date"]).days > 366:
            raise serializers.ValidationError({"end_date": ["An absence can be at most a year long."]})
        if attrs.get("periods") and attrs["end_date"] != attrs["start_date"]:
            raise serializers.ValidationError({"periods": ["Choose periods only for a one-day absence."]})
        return attrs
