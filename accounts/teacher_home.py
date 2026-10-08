"""
A teacher's home page: their classes at a glance, and a getting-started
checklist that ticks itself as they use HouseMaster for the first time.
Also records when someone has been through the guided tour.
"""
from collections import defaultdict

from django.utils import timezone
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from activity.models import ActivityLog
from attendance.models import AttendanceRecord
from messaging.models import Message
from students.localtime import school_localdate
from students.presets import SHORT_NAMES, section_for, school_vocab

from .permissions import HasSchoolProfile


def _did(user, *actions):
    return ActivityLog.objects.filter(actor=user, action__in=actions).exists()


def _step(key, title, detail, done, tab):
    return {"key": key, "title": title, "detail": detail, "done": bool(done), "tab": tab}


def teacher_checklist(profile):
    user, school = profile.user, profile.school
    words = school_vocab(school)
    class_teacher = profile.assignments.filter(subject__isnull=True).exists()
    steps = [
        _step("tour", "Take the guided tour", "A two-minute walk through every part of HouseMaster.",
              profile.tour_seen_at, "home"),
        _step("register", "Take your first register",
              f"Mark who's present in one of your {words['classes'].lower()}. It takes a minute each morning.",
              _did(user, "attendance.created", "attendance.updated"), "attendance"),
        _step("marks", "Record some marks",
              f"Enter marks for a test or assignment; each {words['subject'].lower()}'s result and level update as you go.",
              _did(user, "grade.created", "grade.updated"), "grades"),
        _step("comments", "Write report card comments",
              f"Add a comment for each student in the {words['subjects'].lower()} you teach; they go on the report card.",
              _did(user, "subject_report.saved"), "grades"),
    ]
    if class_teacher:
        steps.append(_step("reports", "Draft end-of-term reports",
                           f"As a class teacher, draft reports for your {words['class'].lower()} (with AI help if you "
                           "like) and send them to an admin to finalize.",
                           _did(user, "report.generated", "report.class_generated", "report.class_submitted"),
                           "reports"))
    steps.append(_step("message", "Get in touch with parents",
                       f"Message a parent, or send a notice to your whole {words['class'].lower()}.",
                       Message.objects.filter(sender=user).exists()
                       or _did(user, "class_message.created", "announcement.created", "announcement.published"),
                       "messages"))
    return {"hidden": profile.checklist_hidden, "steps": steps,
            "done": sum(s["done"] for s in steps), "total": len(steps)}


def teacher_classes(profile):
    """Each class the teacher is assigned to, with what they teach there and whether today's register is in."""
    school = profile.school
    # The curriculum is only worth showing in a school running more than one.
    mixed = school.year_groups.exclude(education_system="").exclude(education_system=school.education_system).exists()
    classes = {}
    for a in profile.assignments.select_related("school_class__year_group", "subject"):
        klass = a.school_class
        row = classes.setdefault(klass.id, {
            "id": klass.id, "name": klass.name, "year_group": klass.year_group.name,
            "curriculum": SHORT_NAMES.get(section_for(klass.year_group, school)[0], "") if mixed else "",
            "class_teacher": False, "subjects": [],
        })
        if a.subject is None:
            row["class_teacher"] = True
        else:
            row["subjects"].append(a.subject.name)
    today = school_localdate(school)
    for row in classes.values():
        students = list(school.students.filter(school_class_id=row["id"], is_active=True).values_list("id", flat=True))
        row["students"] = len(students)
        row["register_taken_today"] = AttendanceRecord.objects.filter(student_id__in=students, date=today).exists()
        row["subjects"].sort()
    return sorted(classes.values(), key=lambda r: (r["year_group"], r["name"]))


@api_view(["GET", "PATCH"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def teacher_home(request):
    """GET: the signed-in teacher's classes and getting-started checklist. PATCH {hidden}: hide or show the checklist."""
    profile = request.user.profile
    if request.method == "PATCH":
        hidden = request.data.get("hidden")
        if not isinstance(hidden, bool):
            raise ValidationError({"hidden": "Send true or false."})
        profile.checklist_hidden = hidden
        profile.save(update_fields=["checklist_hidden"])
    return Response({"classes": teacher_classes(profile), "checklist": teacher_checklist(profile),
                     "support": support_summary(request.user), "today": _today(request.user),
                     "boarding": _boarding(request.user)})


def support_summary(user):
    """Students the teacher can see: how many are suggested for support, and reviews that are due."""
    from accounts.scoping import visible_students
    from activity.services import student_name
    from reporting.analytics import SchoolGrades
    from support.models import SupportConcern
    from support.services import suggestions

    school = user.profile.school
    visible = visible_students(user).filter(is_active=True)
    data = SchoolGrades(school, recent=True)
    ids = [sid for sid in visible.values_list("id", flat=True) if sid in data.students]
    open_concerns = SupportConcern.objects.filter(student__in=visible, status=SupportConcern.Status.OPEN)
    due = open_concerns.filter(review_date__lte=school_localdate(school)).select_related("student")
    return {
        "suggested": len(suggestions(data, data.term(None), ids)),
        "open": open_concerns.count(),
        "due": [{"id": c.id, "student": c.student_id, "student_name": student_name(c.student),
                 "review_date": c.review_date} for c in due.order_by("review_date")],
    }


@api_view(["POST"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def tour_seen(request):
    """Record that the signed-in staff member has been through (or skipped) the guided tour."""
    profile = request.user.profile
    if profile.tour_seen_at is None:
        profile.tour_seen_at = timezone.now()
        profile.save(update_fields=["tour_seen_at"])
    return Response({"tour_seen": True})


def _today(user):
    """The teacher's lessons today, from the timetable."""
    from timetable.views import today_for

    return today_for(user.profile)


def _boarding(user):
    """For boarding staff: who's missing, leave waiting and who's in sick bay."""
    from boarding.services import is_boarding_staff, overview

    return overview(user) if is_boarding_staff(user) else None


def _rank(values, mine):
    """Competition ranking (1, 2, 2, 4) of `mine` among `values`, highest first, on the shown (1 dp) figures."""
    if mine is None:
        return None
    return 1 + sum(1 for v in values if v is not None and v > mine)


def class_performance(user, term_id=None):
    """
    How each of this teacher's classes is doing this term, compared with the
    other classes in its year group: the class average and its position, and
    for each subject the class's average, the year group's and its position.
    Other classes are counted but never named.
    """
    from reporting.analytics import SchoolGrades
    from students.models import SchoolClass

    from .scoping import ACADEMIC, scope_class_ids

    profile = user.profile
    school = profile.school
    # Classes they teach; plus a Class Teacher's class and a Head of Year's year (leaders: just what they teach).
    mine = set(profile.assignments.values_list("school_class_id", flat=True))
    scope = scope_class_ids(user, ACADEMIC)
    if scope is not None:
        mine |= scope
    data = SchoolGrades(school, recent=True, term_id=term_id)
    term = data.term(term_id)
    taught = defaultdict(set)
    for class_id, subject_name, section in profile.assignments.filter(subject__isnull=False).values_list(
            "school_class_id", "subject__name", "subject__education_system"):
        taught[class_id].add((subject_name, section))
    rows = []
    if term is None:
        return {"term": None, "term_name": None, "terms": [], "classes": []}
    classes = SchoolClass.objects.filter(id__in=mine).select_related("year_group").order_by(
        "year_group__order", "year_group__name", "name")
    by_year = defaultdict(list)
    for klass in SchoolClass.objects.filter(year_group__school=school, year_group_id__in={c.year_group_id for c in classes}):
        by_year[klass.year_group_id].append(klass.id)
    cache = {}

    def stats(class_id):
        if class_id not in cache:
            ids = data.in_class(class_id)
            cache[class_id] = (data.group_average(ids, term.id), data.group_subjects(ids, term.id), len(ids))
        return cache[class_id]

    for klass in classes:
        average, subjects, size = stats(klass.id)
        others = [stats(c) for c in by_year[klass.year_group_id]]
        year_ids = data.in_year(klass.year_group_id)
        year_subjects = data.group_subjects(year_ids, term.id)
        subject_rows = []
        for name in sorted(subjects):
            value = subjects[name]
            peers = [o[1].get(name) for o in others if o[1].get(name) is not None]
            base = name.split(" · ")[0]
            subject_rows.append({
                "subject": name, "average": value, "year_average": year_subjects.get(name),
                "rank": _rank(peers, value), "of": len(peers),
                "teaches": any(base == t[0] for t in taught[klass.id]),
            })
        ranked = [o[0] for o in others if o[0] is not None]
        rows.append({
            "id": klass.id, "name": klass.name, "year_group": klass.year_group.name, "students": size,
            "average": average, "year_average": data.group_average(year_ids, term.id),
            "rank": _rank(ranked, average), "of": len(ranked), "subjects": subject_rows,
        })
    return {"term": term.id, "term_name": term.name,
            "terms": [{"id": t.id, "name": t.name} for t in data.graded_terms], "classes": rows}


@api_view(["GET"])
@permission_classes([IsAuthenticated, HasSchoolProfile])
def class_performance_view(request):
    """GET ?term=: the teacher's classes' averages and positions in their year groups (see class_performance)."""
    return Response(class_performance(request.user, request.query_params.get("term")))
