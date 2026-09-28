"""
Data protection requests (Kenya Data Protection Act 2019) for one family:

* family_export: everything the school holds about a student and their
  parents, as an Excel workbook an admin can hand over on request.
* remove_personal_data: removes a family's personal details on request.
  Grades and attendance stay (without notes) under an anonymous name, so
  class averages and past results for everyone else don't change.
"""
import re
from collections import Counter

import openpyxl
from django.db import transaction
from django.db.models import Q

from activity.models import ActivityLog
from activity.services import display_name, log_activity, student_name
from approvals.models import ChangeRequest
from attendance.models import AttendanceRecord
from gradebook.models import Grade, SubjectReport
from guardians.models import Guardian, GuardianInvite, ParentSignupRequest
from messaging.models import Conversation, Message
from reporting.exports import _sheet, _workbook_bytes
from reporting.models import StudentReport

from .presets import school_vocab

REMOVED_FIRST, REMOVED_LAST = "Removed", "student"
REMOVED_NAME = f"{REMOVED_FIRST} {REMOVED_LAST}"


def _when(value):
    return value.replace(tzinfo=None) if value is not None and getattr(value, "tzinfo", None) else value


def family_export(student):
    """An Excel workbook of everything held about this student and their parents."""
    klass = student.school_class
    words = school_vocab(student.school)
    guardians = list(student.guardians.select_related("user"))
    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    _sheet(wb, "Student", ["Field", "Value"], [
        ["School", student.school.name],
        ["First name", student.first_name],
        ["Last name", student.last_name],
        [words["student_id"], student.external_id],
        [words["year_group"], klass.year_group.name if klass else ""],
        [words["class"], klass.name if klass else ""],
        ["House", student.house],
        ["Gender", student.get_gender_display() if student.gender else ""],
        ["Date of birth", student.date_of_birth],
        ["Nationality", student.nationality],
        ["Mode of learning", student.get_mode_of_learning_display() if student.mode_of_learning else ""],
        ["Admission date", student.enrolled_on],
        ["Status", "Active" if student.is_active else "Inactive"],
        ["Health notes", student.medical_notes],
        ["Photo held", "Yes" if student.photo else "No"],
    ], widths={"Field": 20, "Value": 60})

    _sheet(wb, "Parents", [
        "Name", "Email", "Relationship", "Phone", "Second phone", "Home address", "Occupation",
        "Preferred contact", "Email notifications", "Admin note", "Account", "Joined", "Last login",
        "Privacy notice accepted",
    ], [[
        g.name, g.user.email, g.get_relationship_display() if g.relationship else "", g.phone, g.phone_alt,
        g.address, g.occupation, g.get_preferred_contact_display() if g.preferred_contact else "",
        "On" if g.email_notifications else "Off", g.admin_note,
        "Active" if g.user.is_active else "Deactivated", _when(g.user.date_joined), _when(g.user.last_login),
        _when(g.privacy_accepted_at),
    ] for g in guardians], widths={"Home address": 36, "Admin note": 36, "Email": 30})

    _sheet(wb, "Grades", ["Term", "Subject", "Score", "Out of", "Percent", "Recorded"], [
        [g.term.name, g.subject.name, float(g.score), float(g.max_score),
         round(float(g.score) / float(g.max_score) * 100, 1) if g.max_score else None, _when(g.recorded_at)]
        for g in Grade.objects.filter(student=student).select_related("term", "subject").order_by("term_id", "subject__name")
    ])
    _sheet(wb, "Attendance", ["Date", "Status", "Note"], [
        [r.date, r.get_status_display(), r.notes]
        for r in AttendanceRecord.objects.filter(student=student).order_by("date")
    ])
    _sheet(wb, "Reports", ["Term", "Status", "Report comment", "Progress summary (staff)", "Finalized"], [
        [r.term.name, r.get_status_display(), r.report_comment, r.progress_summary, _when(r.finalized_at)]
        for r in StudentReport.objects.filter(student=student).select_related("term").order_by("term_id")
    ], widths={"Report comment": 60, "Progress summary (staff)": 60})

    _sheet(wb, "Messages", ["Sent", "Conversation", "From", "Message"], [
        [_when(m.created_at), m.conversation.get_kind_display(), display_name(m.sender) if m.sender else "Removed",
         m.body]
        for m in _parent_messages(guardians)
    ], widths={"Message": 80})
    _sheet(wb, "Subject comments", ["Term", "Subject", "Comment", "Effort", "Target"], [
        [e.term.name, e.subject.name, e.comment, e.effort, e.target] for e in _subject_comments(student)
    ], widths={"Comment": 80})
    _sheet(wb, "About the student", ["Sent", "From", "Message"], [
        [_when(m.created_at), display_name(m.sender) if m.sender else "Removed", m.body]
        for m in _messages_about(student)
    ], widths={"Message": 80})
    return _workbook_bytes(wb)


def _parent_messages(guardians):
    """Messages the parents sent anywhere, and everything in their direct conversations."""
    users = [g.user for g in guardians]
    return Message.objects.filter(
        Q(sender__in=users) | Q(conversation__kind=Conversation.Kind.DIRECT, conversation__participants__in=users)
    ).select_related("sender", "conversation").distinct().order_by("created_at")


def _subject_comments(student):
    return SubjectReport.objects.filter(student=student).select_related("term", "subject").order_by("term_id",
                                                                                                    "subject__name")


def _messages_about(student):
    """Every message in a conversation about this student, whoever took part."""
    return Message.objects.filter(conversation__student=student).select_related("sender").order_by("created_at")


def _iso(value):
    return value.isoformat() if value is not None and hasattr(value, "isoformat") else value


def family_export_data(student):
    """The same as family_export, as a dict ready to send as JSON."""
    klass = student.school_class
    guardians = list(student.guardians.select_related("user"))
    return {
        "student": {
            "school": student.school.name, "first_name": student.first_name, "last_name": student.last_name,
            "student_id": student.external_id, "year_group": klass.year_group.name if klass else "",
            "class": klass.name if klass else "", "house": student.house, "gender": student.gender,
            "date_of_birth": _iso(student.date_of_birth), "nationality": student.nationality,
            "mode_of_learning": student.mode_of_learning, "admission_date": _iso(student.enrolled_on),
            "active": student.is_active, "health_notes": student.medical_notes, "photo_held": bool(student.photo),
        },
        "parents": [{
            "name": g.name, "email": g.user.email, "relationship": g.relationship, "phone": g.phone,
            "second_phone": g.phone_alt, "home_address": g.address, "occupation": g.occupation,
            "preferred_contact": g.preferred_contact, "email_notifications": g.email_notifications,
            "admin_note": g.admin_note, "account_active": g.user.is_active, "joined": _iso(g.user.date_joined),
            "last_login": _iso(g.user.last_login), "privacy_notice_accepted": _iso(g.privacy_accepted_at),
        } for g in guardians],
        "grades": [{
            "term": g.term.name, "subject": g.subject.name, "score": float(g.score), "out_of": float(g.max_score),
            "recorded": _iso(g.recorded_at),
        } for g in Grade.objects.filter(student=student).select_related("term", "subject").order_by("term_id", "id")],
        "attendance": [{"date": _iso(r.date), "status": r.status, "note": r.notes}
                       for r in AttendanceRecord.objects.filter(student=student).order_by("date")],
        "reports": [{
            "term": r.term.name, "status": r.status, "report_comment": r.report_comment,
            "progress_summary": r.progress_summary, "finalized": _iso(r.finalized_at),
        } for r in StudentReport.objects.filter(student=student).select_related("term").order_by("term_id")],
        "subject_comments": [{"term": e.term.name, "subject": e.subject.name, "comment": e.comment,
                              "effort": e.effort, "target": e.target} for e in _subject_comments(student)],
        "parent_messages": [{"sent": _iso(m.created_at), "from": display_name(m.sender) if m.sender else "Removed",
                             "message": m.body} for m in _parent_messages(guardians)],
        "conversations_about_the_student": [{
            "sent": _iso(m.created_at), "from": display_name(m.sender) if m.sender else "Removed", "message": m.body,
        } for m in _messages_about(student)],
    }


def _scrub(text, old_student_name, parent_names):
    text = text.replace(old_student_name, REMOVED_NAME)
    for name in parent_names:
        text = text.replace(name, "a removed parent")
    return text


def _scrub_child(text, first_name, last_name):
    """
    Replace the child's full name, and their first name as a whole word, in
    text that is about them. A surname on its own is left alone: in text
    like this it is usually a parent's or a sibling's.
    """
    full = f"{first_name} {last_name}".strip()
    if full:
        text = re.sub(re.escape(full), REMOVED_NAME, text, flags=re.IGNORECASE)
    if first_name.strip():
        text = re.sub(rf"\b{re.escape(first_name.strip())}\b", REMOVED_NAME, text)
    return text


@transaction.atomic
def remove_personal_data(student, actor):
    """
    Remove a family's personal details. Parents linked only to this student
    are deleted along with their messages; parents with other children at
    the school keep their account and just lose the link. Returns counts.
    """
    school = student.school
    old_name = student_name(student)
    counts = Counter()

    guardians = list(student.guardians.select_related("user"))
    removed_parent_names = []
    for g in guardians:
        if g.students.exclude(id=student.id).exists():
            g.students.remove(student)
            counts["parents_unlinked"] += 1
            continue
        removed_parent_names.extend(n for n in (g.name, g.user.email) if n)
        direct = Conversation.objects.filter(kind=Conversation.Kind.DIRECT, participants=g.user)
        counts["messages_deleted"] += Message.objects.filter(Q(conversation__in=direct) | Q(sender=g.user)).count()
        Message.objects.filter(sender=g.user).delete()
        direct.delete()
        g.user.delete()  # also deletes the Guardian row
        counts["parents_deleted"] += 1

    for invite in GuardianInvite.objects.filter(students=student):
        if invite.students.exclude(id=student.id).exists():
            invite.students.remove(student)
        else:
            invite.delete()
            counts["invites_deleted"] += 1

    counts["reports_deleted"] = StudentReport.objects.filter(student=student).delete()[0]
    AttendanceRecord.objects.filter(student=student).exclude(notes="").update(notes="")

    # Free text written about this child: their per-subject comments and the
    # messages of conversations about them (the conversations stay, for the
    # other people in them, but no longer point at the child).
    first, last = student.first_name, student.last_name
    for entry in SubjectReport.objects.filter(student=student).exclude(comment=""):
        scrubbed = _scrub_child(entry.comment, first, last)
        if scrubbed != entry.comment:
            entry.comment = scrubbed
            entry.save(update_fields=["comment"])
            counts["subject_comments_scrubbed"] += 1
    for message in Message.objects.filter(conversation__student=student):
        scrubbed = _scrub_child(message.body, first, last)
        if scrubbed != message.body:
            message.body = scrubbed
            message.save(update_fields=["body"])
            counts["messages_scrubbed"] += 1
    Conversation.objects.filter(student=student).update(student=None)
    # Sign-up requests typed by a parent name the child and their admission number.
    counts["signup_requests_deleted"] = ParentSignupRequest.objects.filter(student=student).delete()[0]

    student.first_name, student.last_name = REMOVED_FIRST, REMOVED_LAST
    student.external_id = ""
    student.house = ""
    student.gender = ""
    student.date_of_birth = None
    student.nationality = ""
    student.mode_of_learning = ""
    student.enrolled_on = None
    student.medical_notes = ""
    student.photo = None
    student.photo_updated_at = None
    student.is_active = False
    student.save()

    # Names also appear in the activity log and teachers' requests.
    names = [old_name] + removed_parent_names
    for model in (ActivityLog, ChangeRequest):
        query = Q()
        for name in names:
            query |= Q(summary__contains=name)
        for row in model.objects.filter(query, school=school):
            row.summary = _scrub(row.summary, old_name, removed_parent_names)
            row.save(update_fields=["summary"])
    ChangeRequest.objects.filter(school=school, kind="student", target_id=student.id).update(data={})

    log_activity(
        school=school, actor=actor, action="student.personal_data_removed", target=student,
        summary="Removed a student's personal details at the family's request", **dict(counts),
    )
    return dict(counts)
