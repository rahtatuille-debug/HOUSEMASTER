"""Everything the student profile page shows, gathered in one place."""
from collections import defaultdict
from datetime import date

from django.db.models import Count

from accounts.models import TeachingAssignment
from accounts.scoping import is_admin
from activity.models import ActivityLog
from activity.services import display_name
from attendance.models import AttendanceRecord
from gradebook.models import Grade, Term
from guardians.models import GuardianInvite
from reporting.models import StudentReport

from .models import Student


def _percent(grade):
    return float(grade.score) / float(grade.max_score) * 100 if grade.max_score else None


def _average(values):
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 1) if values else None


def _group_average(students, term):
    """Average of each student's average for the term, so one heavily graded student doesn't dominate."""
    per_student = defaultdict(list)
    for grade in Grade.objects.filter(student__in=students, term=term):
        per_student[grade.student_id].append(_percent(grade))
    return _average([_average(v) for v in per_student.values()])


def _age(dob):
    if not dob:
        return None
    today = date.today()
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
    grades = list(Grade.objects.filter(student=student).select_related("subject", "term"))
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
             "percent": round(_percent(g), 1) if _percent(g) is not None else None}
            for g in term_grades
        ]
        student_avg = _average([_percent(g) for g in term_grades])
        grades_by_term.append({"term": term.name, "term_id": term.id, "average": student_avg, "grades": rows})
        performance.append({
            "term": term.name,
            "student": student_avg,
            "class": _group_average(classmates, term) if classmates is not None else None,
            "year_group": _group_average(year_mates, term) if year_mates is not None else None,
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

    today = date.today()
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

    profile = {
        "class_name": school_class.name if school_class else None,
        "year_group_name": year_group.name if year_group else None,
        "age": _age(student.date_of_birth),
        "teachers": teachers,
        "subjects": subjects,
        "grades_by_term": grades_by_term,
        "performance": performance,
        "attendance": attendance,
        "parents": parents,
        "pending_parent_invites": pending_invites,
        "reports": reports,
        "activity": None,
    }
    if is_admin(user):
        profile["activity"] = [
            {"created_at": e.created_at, "actor_name": e.actor_name, "summary": e.summary}
            for e in ActivityLog.objects.filter(
                school=student.school, target_type="student", target_id=student.id
            )[:20]
        ]
    return profile
