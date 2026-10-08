"""Everything the student profile page shows, gathered in one place."""
from datetime import date

from django.db.models import Count

from accounts.models import TeachingAssignment
from accounts.scoping import ACADEMIC, PASTORAL, can_use_class, is_admin
from activity.models import ActivityLog
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Term
from gradebook.weighting import school_weights, student_average, subject_percents
from guardians.models import GuardianInvite
from reporting.models import StudentReport

from .localtime import school_localdate
from .models import Student


def _percent(grade):
    return float(grade.score) / float(grade.max_score) * 100 if grade.max_score else None


def _average(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _group_average(students, term, weights):
    """Average of each student's average for the term, so one heavily graded student doesn't dominate."""
    per = subject_percents(Grade.objects.filter(student__in=students, term=term), weights, key=lambda g: g.subject_id)
    return _average([student_average(subjects) for subjects in per.values()])


def _age(dob, school):
    if not dob:
        return None
    today = school_localdate(school)
    return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))


def build_profile(student, user):
    school_class = student.school_class
    year_group = school_class.year_group if school_class else None

    # Teachers and subjects for the student's class.
    assignments = (
        TeachingAssignment.objects.filter(school_class=school_class, teacher__user__is_active=True)
        .select_related("teacher", "subject")
        if school_class else TeachingAssignment.objects.none()
    )
    teachers = [
        {"teacher": a.teacher.name, "subject": a.subject.name if a.subject else "All subjects"}
        for a in assignments
    ]

    # Grades, grouped by term, oldest term first.
    grades = list(Grade.objects.filter(student=student).select_related("subject", "term", "assessment_type"))
    weights = school_weights(student.school)
    terms = sorted({g.term for g in grades}, key=lambda t: (t.start_date or date.min, t.id))
    subjects = sorted({g.subject.name for g in grades} | {
        a.subject.name for a in assignments if a.subject
    })

    classmates = Student.objects.filter(school_class=school_class, is_active=True) if school_class else None
    year_mates = (
        Student.objects.filter(school_class__year_group=year_group, is_active=True) if year_group else None
    )
    grades_by_term = []
    performance = []
    for term in terms:
        term_grades = sorted((g for g in grades if g.term_id == term.id), key=lambda g: g.subject.name)
        rows = [
            {"subject": g.subject.name, "score": str(g.score), "max_score": str(g.max_score),
             "percent": round(_percent(g), 1) if _percent(g) is not None else None,
             "assessment": g.assessment_type.name if g.assessment_type else ""}
            for g in term_grades
        ]
        per_subject = subject_percents(term_grades, weights).get((student.id, term.id), {})
        student_avg = _average([student_average(per_subject)])
        grades_by_term.append({"term": term.name, "term_id": term.id, "average": student_avg, "grades": rows})
        performance.append({
            "term": term.name,
            "student": student_avg,
            "class": _group_average(classmates, term, weights) if classmates is not None else None,
            "year_group": _group_average(year_mates, term, weights) if year_mates is not None else None,
        })

    # Attendance: overall, current term, and the latest records.
    records = AttendanceRecord.objects.filter(student=student)

    def summary(queryset):
        counts = dict(queryset.values_list("status").annotate(n=Count("id")))
        total = sum(counts.values())
        attended = counts.get("present", 0) + counts.get("late", 0)
        return {
            "total": total,
            "present": counts.get("present", 0),
            "absent": counts.get("absent", 0),
            "late": counts.get("late", 0),
            "excused": counts.get("excused", 0),
            "rate": round(attended / total * 100, 1) if total else None,
        }

    today = school_localdate(student.school)
    current_term = Term.objects.filter(
        school=student.school, start_date__lte=today, end_date__gte=today
    ).first()
    attendance = {
        "overall": summary(records),
        "current_term": (
            {"term": current_term.name, **summary(records.filter(
                date__gte=current_term.start_date, date__lte=current_term.end_date))}
            if current_term else None
        ),
        "recent": [
            {"date": r.date, "status": r.status, "notes": r.notes}
            for r in records.order_by("-date")[:10]
        ],
    }

    # Parents with accounts, and invites that haven't been accepted yet.
    # Everyone who can see the student sees how to reach the parents; the
    # address, occupation and admin note are for admins only.
    admin = is_admin(user)
    parents = []
    for g in student.guardians.select_related("user"):
        parent = {
            "id": g.id, "name": g.name, "email": g.user.email, "is_active": g.user.is_active,
            "last_login": g.user.last_login, "user_id": g.user_id,
            "phone": g.phone, "phone_alt": g.phone_alt, "relationship": g.relationship,
            "preferred_contact": g.preferred_contact,
        }
        if admin:
            parent.update(address=g.address, occupation=g.occupation, admin_note=g.admin_note)
        parents.append(parent)
    pending_invites = [
        {"name": inv.name, "email": inv.email, "status": inv.status}
        for inv in GuardianInvite.objects.filter(students=student, accepted_at__isnull=True)
    ]

    reports = [
        {"id": r.id, "term": r.term.name, "status": r.status, "finalized_at": r.finalized_at,
         "report_comment": r.report_comment}
        for r in StudentReport.objects.filter(student=student).select_related("term").order_by("-generated_at")
    ]

    # Staff see each part of the profile only if their role covers it for this
    # student (accounts.scoping); parents' views pick their own fields.
    staff = getattr(user, "profile", None) is not None
    academic = not staff or can_use_class(user, student.school_class_id, ACADEMIC)
    pastoral = not staff or can_use_class(user, student.school_class_id, PASTORAL)
    if not academic:
        grades_by_term, performance, reports = [], [], []
    if not pastoral:
        attendance = None

    profile = {
        "class_name": school_class.name if school_class else None,
        "year_group_name": year_group.name if year_group else None,
        "age": _age(student.date_of_birth, student.school),
        "teachers": teachers,
        "subjects": subjects,
        "grades_by_term": grades_by_term,
        "performance": performance,
        "attendance": attendance,
        "parents": parents,
        "pending_parent_invites": pending_invites,
        "reports": reports,
        "activity": None,
        # Staff only: the guardians' view picks its own fields and never this.
        "support": _support(student) if pastoral else None,
        "discipline": _discipline(student) if pastoral else None,
        "merits": _merits(student) if pastoral else None,
        "clubs": [{"id": m.club_id, "name": m.club.name, "role": m.role}
                  for m in student.club_memberships.filter(club__is_active=True).select_related("club")
                  .order_by("club__name")],
        # Which parts this person may see, so the page can say so.
        "sections": {"academic": academic, "pastoral": pastoral},
        "boarding": _boarding(student),
    }
    if is_admin(user):
        profile["activity"] = [
            {"created_at": e.created_at, "actor_name": e.actor_name, "summary": e.summary}
            for e in ActivityLog.objects.filter(
                school=student.school, target_type="student", target_id=student.id
            )[:20]
        ]
    return profile


def _support(student):
    """The open support concern and the history of confirmed ones (support app)."""
    from support.models import SupportConcern
    from support.serializers import SupportConcernSerializer

    concerns = list(student.support_concerns.exclude(status=SupportConcern.Status.DISMISSED)
                    .select_related("student__school_class__year_group", "term"))
    open_one = next((c for c in concerns if c.status == SupportConcern.Status.OPEN), None)
    return {"open": SupportConcernSerializer(open_one).data if open_one else None,
            "history": SupportConcernSerializer(concerns, many=True).data}


def _discipline(student):
    """The student's latest behaviour records (discipline app). Staff only."""
    from discipline.serializers import DisciplineIncidentSerializer

    incidents = student.discipline_incidents.select_related("student__school_class")
    return {"count": incidents.count(), "recent": DisciplineIncidentSerializer(incidents[:10], many=True).data}


def _merits(student):
    """The student's merit points and latest merits (discipline app). Staff only."""
    from django.db.models import Count, Sum

    from discipline.serializers import MeritSerializer

    merits = student.merits.select_related("student__school_class")
    totals = merits.aggregate(count=Count("id"), points=Sum("points"))
    return {"count": totals["count"], "points": totals["points"] or 0,
            "recent": MeritSerializer(merits[:10], many=True).data}


def _boarding(student):
    """A flag for staff when a boarder has no bed yet (e.g. arrived from admissions). None otherwise."""
    if student.school.has_boarding and student.is_active and student.mode_of_learning == "boarding" \
            and not hasattr(student, "bed"):
        return {"boarder_without_bed": True}
    return None
