from rest_framework import viewsets

from accounts.mixins import SchoolScopedViewSetMixin
from activity.services import log_activity, student_name

from .models import Subject, Term, Grade
from .serializers import SubjectSerializer, TermSerializer, GradeSerializer


class SubjectViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Subject.objects.all()
    serializer_class = SubjectSerializer
    school_lookup = "school"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class TermViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Term.objects.all()
    serializer_class = TermSerializer
    school_lookup = "school"

    def perform_create(self, serializer):
        serializer.save(school=self.get_school())

    def perform_update(self, serializer):
        serializer.save(school=self.get_school())


class GradeViewSet(SchoolScopedViewSetMixin, viewsets.ModelViewSet):
    queryset = Grade.objects.all()
    serializer_class = GradeSerializer
    filterset_fields = ["student", "subject", "term"]
    school_lookup = "student__school"

    def _validate_related(self, validated_data):
        self.check_belongs_to_school(validated_data["student"].school, "student")
        self.check_belongs_to_school(validated_data["subject"].school, "subject")
        self.check_belongs_to_school(validated_data["term"].school, "term")

    @staticmethod
    def _describe(grade):
        return f"{grade.subject.name} grade for {student_name(grade.student)} ({grade.term.name})"

    def perform_create(self, serializer):
        self._validate_related(serializer.validated_data)
        grade = serializer.save()
        log_activity(
            school=self.get_school(), actor=self.request.user, action="grade.created", target=grade,
            summary=f"Added {self._describe(grade)}: {grade.score}/{grade.max_score}",
            score=str(grade.score), max_score=str(grade.max_score),
        )

    def perform_update(self, serializer):
        student = serializer.validated_data.get("student", serializer.instance.student)
        subject = serializer.validated_data.get("subject", serializer.instance.subject)
        term = serializer.validated_data.get("term", serializer.instance.term)
        self.check_belongs_to_school(student.school, "student")
        self.check_belongs_to_school(subject.school, "subject")
        self.check_belongs_to_school(term.school, "term")
        old = f"{serializer.instance.score}/{serializer.instance.max_score}"
        grade = serializer.save()
        new = f"{grade.score}/{grade.max_score}"
        log_activity(
            school=self.get_school(), actor=self.request.user, action="grade.updated", target=grade,
            summary=f"Changed {self._describe(grade)} from {old} to {new}",
            old=old, new=new,
        )

    def perform_destroy(self, instance):
        log_activity(
            school=self.get_school(), actor=self.request.user, action="grade.deleted", target=instance,
            summary=f"Deleted {self._describe(instance)} ({instance.score}/{instance.max_score})",
            score=str(instance.score), max_score=str(instance.max_score),
        )
        instance.delete()
