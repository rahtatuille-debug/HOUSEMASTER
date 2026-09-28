from rest_framework import serializers
from accounts.mixins import SchoolScopedRelatedFieldsMixin
from .models import AssessmentType, Subject, Term, Grade


class SubjectSerializer(serializers.ModelSerializer):
    # The curriculum it belongs to, and a name that says so in a school running two.
    section = serializers.SerializerMethodField()
    label = serializers.SerializerMethodField()

    class Meta:
        model = Subject
        fields = ["id", "school", "name", "label", "credits", "is_elective", "education_system", "section"]
        extra_kwargs = {"school": {"read_only": True}, "education_system": {"required": False}}

    def get_section(self, obj):
        return obj.education_system or obj.school.education_system

    def get_label(self, obj):
        from students.presets import SHORT_NAMES

        return f"{obj.name} · {SHORT_NAMES.get(obj.education_system, obj.education_system)}" \
            if obj.education_system else obj.name

    def validate_education_system(self, value):
        from accounts.mixins import requester_school
        from students.presets import SYSTEMS, subject_key

        if value and value not in SYSTEMS:
            raise serializers.ValidationError("Choose one of the education systems.")
        return subject_key(requester_school(self.context.get("request")), value)

    def validate(self, attrs):
        from accounts.mixins import requester_school

        school = requester_school(self.context.get("request"))
        name = attrs.get("name", getattr(self.instance, "name", None))
        system = attrs.get("education_system", getattr(self.instance, "education_system", ""))
        clash = Subject.objects.filter(school=school, name__iexact=name, education_system=system)
        if self.instance:
            clash = clash.exclude(pk=self.instance.pk)
        if name and clash.exists():
            raise serializers.ValidationError({"name": f"There's already a subject called {name} in that curriculum."})
        return attrs


class AssessmentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssessmentType
        fields = ["id", "school", "name", "weight", "order"]
        extra_kwargs = {"school": {"read_only": True}}

    def validate_weight(self, value):
        if value < 0 or value > 100:
            raise serializers.ValidationError("A weight is a percentage from 0 to 100.")
        return value


class TermSerializer(serializers.ModelSerializer):
    class Meta:
        model = Term
        fields = ["id", "school", "name", "start_date", "end_date", "is_locked", "locked_at"]
        extra_kwargs = {"school": {"read_only": True}, "is_locked": {"read_only": True},
                        "locked_at": {"read_only": True}}


class GradeSerializer(SchoolScopedRelatedFieldsMixin, serializers.ModelSerializer):
    class Meta:
        model = Grade
        fields = ["id", "student", "subject", "term", "score", "max_score", "assessment_type", "recorded_at"]

    def validate(self, attrs):
        # Check the pair as it will be saved, so an update to only one of
        # them can't leave an impossible mark behind.
        instance = self.instance
        score = attrs.get("score", instance.score if instance else None)
        max_score = attrs.get("max_score", instance.max_score if instance else Grade._meta.get_field("max_score").default)
        if max_score is not None and max_score <= 0:
            raise serializers.ValidationError({"max_score": "The maximum mark must be more than 0."})
        if score is not None and score < 0:
            raise serializers.ValidationError({"score": "A mark can't be below 0."})
        if score is not None and max_score is not None and score > max_score:
            raise serializers.ValidationError({"score": f"A mark can't be more than the maximum ({max_score:g})."})
        return attrs