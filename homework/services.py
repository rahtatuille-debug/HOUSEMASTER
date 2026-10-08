"""Who may set homework, who it is for, and what a student or parent sees."""
from datetime import timedelta

from django.db.models import Q

from accounts.models import TeachingAssignment
from accounts.scoping import department_subject_ids, is_leader
from students.localtime import school_localdate
from students.models import Student

from .models import Assignment, HomeworkRecord


def can_set(user, school_class, subject):
    """Leadership, the subject's Head of Department, or a teacher of that class and subject."""
    if is_leader(user) or subject.id in department_subject_ids(user):
        return True
    return TeachingAssignment.objects.filter(Q(subject=subject) | Q(subject__isnull=True), teacher=user.profile,
                                             school_class=school_class).exists()


def can_change(user, assignment):
    return assignment.set_by_id == user.id or can_set(user, assignment.school_class, assignment.subject)


def students_for(assignment):
    """The class's active students who take the subject (everyone for a core subject)."""
    students = Student.objects.filter(school_class=assignment.school_class, is_active=True)
    if assignment.subject.is_elective:
        students = students.filter(subject_choices__subject=assignment.subject)
    return students.order_by("last_name", "first_name", "id")


def assignments_for_student(student):
    """Homework set for this student's class in subjects they take."""
    if not student.school_class_id:
        return Assignment.objects.none()
    return (Assignment.objects.filter(school_class=student.school_class_id)
            .filter(Q(subject__is_elective=False) | Q(subject__student_choices__student=student))
            .distinct().select_related("subject"))


def record_row(record):
    if record is None:
        return {"status": "", "status_label": "", "mark": None, "comment": "", "done_at": None, "answer": ""}
    return {"status": record.status, "status_label": record.get_status_display() if record.status else "",
            "mark": record.mark, "comment": record.comment, "done_at": record.done_at, "answer": record.answer}


def student_view(student, days_back=30):
    """For the student and their parents: homework due from a month ago on, soonest first, with how it went."""
    today = school_localdate(student.school)
    items = list(assignments_for_student(student).filter(due_date__gte=today - timedelta(days=days_back))
                 .order_by("due_date", "id"))
    records = {r.assignment_id: r for r in HomeworkRecord.objects.filter(student=student, assignment__in=items)}
    return [{
        "id": a.id, "title": a.title, "subject": a.subject.name, "instructions": a.instructions, "link": a.link,
        "set_on": a.set_on, "due_date": a.due_date, "out_of": a.out_of, "set_by_name": a.set_by_name,
        "overdue": a.due_date < today and not (records.get(a.id) and (records[a.id].status or records[a.id].done_at)),
        **record_row(records.get(a.id)),
    } for a in items]
