from django.db import transaction
from django.db.models import Count, Q
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from accounts.permissions import HasSchoolProfile
from accounts.scoping import ACADEMIC, scope_class_ids
from activity.services import display_name, log_activity, student_name
from gradebook.models import Subject
from students.localtime import school_localdate
from students.models import SchoolClass

from . import services
from .models import Assignment, HomeworkRecord

FIELDS = ("title", "instructions", "link", "set_on", "due_date", "out_of")


class AssignmentSerializer(serializers.ModelSerializer):
    class_name = serializers.CharField(source="school_class.name", read_only=True)
    subject_name = serializers.CharField(source="subject.name", read_only=True)
    counts = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = Assignment
        fields = ["id", "school_class", "class_name", "subject", "subject_name", "title", "instructions", "link",
                  "set_on", "due_date", "out_of", "set_by_name", "counts", "can_edit"]
        read_only_fields = ["school_class", "subject", "set_by_name"]
        extra_kwargs = {"instructions": {"max_length": 4000}}

    def get_counts(self, obj):
        """How many students it's for, and how many of each status (and marked done by the student)."""
        ids = set(services.students_for(obj).values_list("id", flat=True))
        records = [r for r in obj.records.all() if r.student_id in ids]
        counts = {s: sum(1 for r in records if r.status == s) for s in HomeworkRecord.Status.values}
        return {"students": len(ids), **counts, "done_by_student": sum(1 for r in records if r.done_at),
                "not_recorded": len(ids) - sum(1 for r in records if r.status)}

    def get_can_edit(self, obj):
        request = self.context.get("request")
        return bool(request and services.can_change(request.user, obj))

    def validate_title(self, value):
        if not value.strip():
            raise serializers.ValidationError("Give the homework a title.")
        return value.strip()

    def validate(self, attrs):
        get = lambda k: attrs.get(k, getattr(self.instance, k, None))  # noqa: E731
        if get("set_on") and get("due_date") and get("due_date") < get("set_on"):
            raise serializers.ValidationError({"due_date": ["It can't be due before it's set."]})
        if get("out_of") == 0:
            raise serializers.ValidationError({"out_of": ["Leave it blank, or give a number above 0."]})
        return attrs


class AssignmentViewSet(viewsets.ModelViewSet):
    """
    Homework. Staff see the homework for the classes they teach (leadership:
    everyone). Set it with POST {school_class, subject, title, instructions,
    link, set_on?, due_date, out_of?}: leadership, the subject's Head of
    Department or a teacher of that class and subject. The person who set it
    or another teacher of that class and subject may change or remove it.
    Filter with ?school_class=, ?subject=, ?mine=1, ?when=upcoming|past.
    """

    serializer_class = AssignmentSerializer
    permission_classes = [IsAuthenticated, HasSchoolProfile]
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        queryset = (Assignment.objects.filter(school=user.profile.school)
                    .select_related("school_class", "subject").prefetch_related("records"))
        scope = scope_class_ids(user, ACADEMIC)
        if scope is not None:
            queryset = queryset.filter(Q(school_class_id__in=scope) | Q(set_by=user))
        params = self.request.query_params
        for field in ("school_class", "subject"):
            if params.get(field):
                queryset = queryset.filter(**{field: params[field]})
        if params.get("mine"):
            queryset = queryset.filter(set_by=user)
        today = school_localdate(user.profile.school)
        if params.get("when") == "upcoming":
            queryset = queryset.filter(due_date__gte=today).order_by("due_date", "id")
        elif params.get("when") == "past":
            queryset = queryset.filter(due_date__lt=today)
        return queryset

    def create(self, request, *args, **kwargs):
        user = request.user
        school = user.profile.school
        try:
            klass = SchoolClass.objects.get(pk=request.data.get("school_class"), year_group__school=school)
            subject = Subject.objects.get(pk=request.data.get("subject"), school=school)
        except (SchoolClass.DoesNotExist, Subject.DoesNotExist, ValueError, TypeError):
            raise ValidationError({"school_class": ["Choose one of your classes and a subject."]})
        if not services.can_set(user, klass, subject):
            raise PermissionDenied(f"You don't teach {subject.name} to {klass.name}.")
        data = {k: v for k, v in request.data.items() if k in FIELDS}
        data.setdefault("set_on", school_localdate(school).isoformat())
        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save(school=school, school_class=klass, subject=subject, set_by=user,
                                     set_by_name=display_name(user))
        log_activity(school=school, actor=user, action="homework.set", target=klass,
                     summary=f"Set {subject.name} homework for {klass.name}: {assignment.title}")
        return Response(self.get_serializer(assignment).data, status=201)

    def _check(self, assignment):
        if not services.can_change(self.request.user, assignment):
            raise PermissionDenied("Only the teacher who set it, another teacher of the class and subject, or leadership can change it.")

    def partial_update(self, request, *args, **kwargs):
        assignment = self.get_object()
        self._check(assignment)
        serializer = self.get_serializer(assignment, data={k: v for k, v in request.data.items() if k in FIELDS}, partial=True)
        serializer.is_valid(raise_exception=True)
        assignment = serializer.save()
        log_activity(school=assignment.school, actor=request.user, action="homework.changed", target=assignment.school_class,
                     summary=f"Changed {assignment.subject.name} homework for {assignment.school_class.name}: {assignment.title}")
        return Response(self.get_serializer(assignment).data)

    def update(self, request, *args, **kwargs):
        return self.partial_update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        assignment = self.get_object()
        self._check(assignment)
        summary = f"Removed {assignment.subject.name} homework for {assignment.school_class.name}: {assignment.title}"
        school, klass = assignment.school, assignment.school_class
        assignment.delete()
        log_activity(school=school, actor=request.user, action="homework.removed", target=klass, summary=summary)
        return Response(status=204)

    @action(detail=True, methods=["get", "post"])
    def records(self, request, pk=None):
        """
        GET: each student it's for, with how they did (and what they handed in).
        POST {records: [{student, status, mark?, comment?}]}: record them
        (status blank to clear). Only teachers who may change the homework.
        """
        assignment = self.get_object()
        if request.method == "POST":
            self._check(assignment)
            self._save(request, assignment)
            assignment = self.get_queryset().get(pk=assignment.pk)  # the counts as they are now
        students = list(services.students_for(assignment))
        records = {r.student_id: r for r in assignment.records.filter(student__in=students)}
        return Response({"assignment": self.get_serializer(assignment).data, "students": [
            {"student": s.id, "name": student_name(s), **services.record_row(records.get(s.id))} for s in students]})

    def _save(self, request, assignment):
        rows = request.data.get("records")
        if not isinstance(rows, list) or not rows:
            raise ValidationError({"records": ["Record at least one student."]})
        allowed = set(services.students_for(assignment).values_list("id", flat=True))
        clean = {}
        for row in rows:
            try:
                sid = int(row.get("student"))
            except (AttributeError, TypeError, ValueError):
                raise ValidationError({"records": ["Student not found."]})
            if sid not in allowed:
                raise ValidationError({"records": ["Only the students this homework is for."]})
            status = row.get("status") or ""
            if status and status not in HomeworkRecord.Status.values:
                raise ValidationError({"records": ["Choose handed in, late, missing or excused."]})
            mark = row.get("mark")
            if mark in ("", None):
                mark = None
            else:
                try:
                    mark = round(float(mark), 1)
                except (TypeError, ValueError):
                    raise ValidationError({"records": ["A mark must be a number."]})
                if mark < 0 or (assignment.out_of and mark > assignment.out_of):
                    raise ValidationError({"records": [f"Marks go from 0 to {assignment.out_of or 'any number'}."]})
            clean[sid] = {"status": status, "mark": mark, "comment": str(row.get("comment") or "").strip()[:1000]}
        with transaction.atomic():
            for sid, values in clean.items():
                HomeworkRecord.objects.update_or_create(assignment=assignment, student_id=sid, defaults=values)
        log_activity(school=assignment.school, actor=request.user, action="homework.recorded", target=assignment.school_class,
                     summary=f"Recorded {assignment.subject.name} homework for {len(clean)} student"
                             f"{'' if len(clean) == 1 else 's'} in {assignment.school_class.name}: {assignment.title}")

    @action(detail=False, methods=["get"])
    def choices(self, request):
        """The classes and subjects this person can set homework for: [{school_class, class_name, subject, subject_name}]."""
        from accounts.models import TeachingAssignment
        from accounts.scoping import department_subject_ids, is_leader

        user = request.user
        school = user.profile.school
        pairs = set()
        classes = SchoolClass.objects.filter(year_group__school=school)
        subjects = Subject.objects.filter(school=school)
        if is_leader(user):
            pairs = {(c, s) for c in classes for s in subjects}
        else:
            for t in TeachingAssignment.objects.filter(teacher=user.profile).select_related("school_class", "subject"):
                for s in ([t.subject] if t.subject_id else subjects):
                    pairs.add((t.school_class, s))
            heads = department_subject_ids(user)
            if heads:
                pairs |= {(c, s) for c in classes for s in subjects if s.id in heads}
        rows = sorted(({"school_class": c.id, "class_name": c.name, "subject": s.id, "subject_name": s.name} for c, s in pairs),
                      key=lambda r: (r["class_name"], r["subject_name"]))
        return Response(rows)


def homework_to_mark(user):
    """For the teacher's Home page: homework they set, due in the last two weeks, with students not yet recorded."""
    from datetime import timedelta

    today = school_localdate(user.profile.school)
    rows = []
    for a in (Assignment.objects.filter(set_by=user, due_date__lte=today, due_date__gte=today - timedelta(days=14))
              .select_related("school_class", "subject").annotate(recorded=Count("records", filter=~Q(records__status="")))
              .order_by("-due_date")[:10]):
        total = services.students_for(a).count()
        if total > a.recorded:
            rows.append({"id": a.id, "title": a.title, "class_name": a.school_class.name, "subject": a.subject.name,
                         "due_date": a.due_date, "to_record": total - a.recorded, "students": total})
    return rows[:5]
