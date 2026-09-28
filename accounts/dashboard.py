"""The admin home page: what needs attention at the school today."""
from datetime import timedelta

from django.db.models import Count, Q
from django.utils import timezone

from approvals.models import ChangeRequest
from attendance.models import AttendanceRecord
from communications.models import UrgentAlert
from guardians.models import GuardianInvite
from reporting.models import StudentReport
from students.models import SchoolClass, Student

from .models import Invite


def _invite_row(invite, kind):
    return {"id": invite.id, "kind": kind, "name": invite.name, "email": invite.email,
            "status": invite.status, "created_at": invite.created_at}


def build_dashboard(school):
    today = timezone.localdate()
    # At weekends, show the last school day's registers instead of warning
    # that none were taken today.
    register_day = today - timedelta(days=max(0, today.weekday() - 4))
    students = Student.objects.filter(school=school, is_active=True)

    # Today's register, class by class.
    per_class = {
        row["student__school_class"]: row
        for row in AttendanceRecord.objects.filter(student__in=students, date=register_day)
        .values("student__school_class")
        .annotate(
            marked=Count("id"),
            present=Count("id", filter=Q(status="present")),
            late=Count("id", filter=Q(status="late")),
            absent=Count("id", filter=Q(status="absent")),
            excused=Count("id", filter=Q(status="excused")),
        )
    }
    class_sizes = dict(
        students.values("school_class").annotate(n=Count("id")).values_list("school_class", "n")
    )
    classes = []
    for school_class in SchoolClass.objects.filter(year_group__school=school).select_related("year_group") \
            .order_by("year_group__name", "name"):
        size = class_sizes.get(school_class.id, 0)
        if not size:
            continue
        row = per_class.get(school_class.id, {})
        classes.append({
            "id": school_class.id, "name": school_class.name, "students": size,
            "marked": row.get("marked", 0), "present": row.get("present", 0), "late": row.get("late", 0),
            "absent": row.get("absent", 0), "excused": row.get("excused", 0),
        })
    marked = sum(c["marked"] for c in classes)
    attended = sum(c["present"] + c["late"] for c in classes)
    attendance = {
        "date": register_day,
        "is_today": register_day == today,
        "students": sum(c["students"] for c in classes),
        "marked": marked,
        "absent": sum(c["absent"] for c in classes),
        "rate": round(attended / marked * 100, 1) if marked else None,
        "classes_not_taken": [c["name"] for c in classes if c["marked"] == 0],
        "classes": classes,
    }

    reports = StudentReport.objects.filter(student__school=school, status="submitted") \
        .select_related("student", "term").order_by("submitted_at")
    change_requests = ChangeRequest.objects.filter(school=school, status=ChangeRequest.Status.PENDING)

    invites = [_invite_row(i, "staff") for i in Invite.objects.filter(school=school, accepted_at__isnull=True)] + \
        [_invite_row(i, "parent") for i in GuardianInvite.objects.filter(school=school, accepted_at__isnull=True)]
    invites.sort(key=lambda i: i["created_at"], reverse=True)

    # Active students with no active parent account linked.
    without_parent = students.exclude(guardians__user__is_active=True).select_related("school_class") \
        .order_by("last_name", "first_name")

    return {
        "attendance_today": attendance,
        "reports_waiting": {
            "count": reports.count(),
            "items": [
                {"id": r.id, "student": f"{r.student.first_name} {r.student.last_name}", "term": r.term.name,
                 "submitted_at": r.submitted_at}
                for r in reports[:10]
            ],
        },
        "requests_waiting": change_requests.count(),
        "parent_signups_waiting": school.signup_requests.filter(status="pending").count(),
        "invites": {
            "pending": sum(1 for i in invites if i["status"] == "pending"),
            "expired": sum(1 for i in invites if i["status"] == "expired"),
            "items": invites[:10],
        },
        "students_without_parent": {
            "count": without_parent.count(),
            "total_students": students.count(),
            "items": [
                {"id": s.id, "name": f"{s.first_name} {s.last_name}",
                 "class_name": s.school_class.name if s.school_class else None}
                for s in without_parent[:20]
            ],
        },
        "active_alerts": [
            {"id": a.id, "title": a.title, "created_at": a.created_at,
             "seen": a.recipients.filter(acknowledged_at__isnull=False).count(), "total": a.recipients.count()}
            for a in UrgentAlert.objects.filter(school=school, ended_at__isnull=True)
        ],
    }
