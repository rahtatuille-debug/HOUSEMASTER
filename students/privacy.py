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
    _sheet(wb, "Support", ["Marked", "Status", "Term", "Reasons", "Note", "Support plan", "Review date", "Closed"], [
        [_when(c.created_at), c.get_status_display(), c.term.name if c.term else "",
         "; ".join(r.get("label", "") for r in c.reasons), c.note, c.support_plan,
         c.review_date.isoformat() if c.review_date else "", _when(c.closed_at) if c.closed_at else ""]
        for c in student.support_concerns.select_related("term").order_by("created_at")
    ], widths={"Note": 50, "Support plan": 60})
    _sheet(wb, "Boarding", ["Kind", "What", "From", "To", "Details", "Status"], [
        ["Leave", l.get_kind_display(), _when(l.leaving_at), _when(l.returning_at),
         "; ".join(x for x in (l.reason, l.collected_by, l.decision_note) if x), l.get_status_display()]
        for l in student.leave_requests.order_by("leaving_at")
    ] + [
        ["Sick bay", v.complaint, _when(v.checked_in_at), _when(v.checked_out_at) if v.checked_out_at else "",
         v.treatment, v.get_outcome_display() if v.outcome else "In sick bay"]
        for v in student.sick_bay_visits.order_by("checked_in_at")
    ], widths={"Details": 60, "What": 40})
    _sheet(wb, "Discipline", ["Date", "Category", "Severity", "What happened", "Action", "Action detail",
                              "Staff notes", "Shared with parents", "Recorded by"], [
        [i.date.isoformat(), i.get_category_display(), i.get_severity_display(), i.description,
         i.get_action_display(), i.action_detail, i.staff_notes, "Yes" if i.shared_with_parents else "No",
         i.recorded_by_name]
        for i in student.discipline_incidents.order_by("date", "id")
    ], widths={"What happened": 60, "Staff notes": 50})
    _sheet(wb, "Merits", ["Date", "For", "Points", "Reason", "Shared with parents", "Given by"], [
        [m.date.isoformat(), m.get_category_display(), m.points, m.reason, "Yes" if m.shared_with_parents else "No",
         m.awarded_by_name]
        for m in student.merits.order_by("date", "id")
    ], widths={"Reason": 60})
    _sheet(wb, "Homework", ["Due", "Subject", "Homework", "Recorded as", "Mark", "Teacher's comment", "Marked done",
                            "Answer"], [
        [r.assignment.due_date.isoformat(), r.assignment.subject.name, r.assignment.title,
         r.get_status_display() if r.status else "", r.mark, r.comment, _when(r.done_at) if r.done_at else "", r.answer]
        for r in _homework(student)
    ], widths={"Homework": 40, "Teacher's comment": 50, "Answer": 60})
    _sheet(wb, "Clubs", ["Kind", "Club", "Date", "Details"], [
        ["Member", m.club.name, m.joined_on.isoformat(), m.role] for m in _club_memberships(student)
    ] + [
        ["Register", a.session.club.name, a.session.date.isoformat(), a.get_status_display()] for a in _club_marks(student)
    ] + [
        ["Picked for", f.club.name, f.date.isoformat(), f"v {f.opponent}"] for f in _club_fixtures(student)
    ], widths={"Club": 30, "Details": 40})
    from admissions.services import application_row, applications_about

    rows = [application_row(a) for a in applications_about(student).order_by("created_at")]
    _sheet(wb, "Applications", [k.replace("_", " ").capitalize() for k in (rows[0] if rows else {"reference": 0})],
           [list(r.values()) for r in rows], widths={"Health and learning needs": 50, "Family notes": 50,
                                                     "Staff notes": 50, "Decision note": 50})
    bed = _bed(student)
    current = [["Bed now", "", bed["house"], f"{bed['dorm']} {bed['bed']}", ""]] if bed else []
    _sheet(wb, "Roll calls", ["Date", "Session", "Boarding house", "Mark", "Note"], current + [
        [e.roll_call.date.isoformat(), e.roll_call.get_session_display(), e.roll_call.house.name,
         e.get_status_display(), e.note] for e in _roll_call_marks(student)
    ] + [
        [_when(a.opened_at), "Marked missing", a.house.name,
         a.get_resolution_display() if a.resolution else "Not found yet", "; ".join(
             x for x in (a.note, a.resolution_note) if x)] for a in _missing_records(student)
    ], widths={"Note": 60})
    _sheet(wb, "Invitations and sign-ups", ["Kind", "Name", "Email", "Sent", "Status"], [
        ["Invitation", i.name, i.email, _when(i.created_at), "Accepted" if i.accepted_at else "Not accepted"]
        for i in _invitations(student)
    ] + [
        ["Sign-up request", r.name, r.email, _when(r.created_at), r.get_status_display()]
        for r in _sign_up_requests(student)
    ])
    _sheet(wb, "Change log", ["When", "By", "What"], [
        [_when(e.created_at), e.actor_name, e.summary] for e in _change_log(student)
    ], widths={"What": 80})
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


def _bed(student):
    bed = getattr(student, "bed", None)
    return {"house": bed.dorm.house.name, "dorm": bed.dorm.name, "bed": bed.name} if bed else None


def _roll_call_marks(student):
    return student.roll_call_entries.exclude(status="").select_related("roll_call__house").order_by(
        "roll_call__date", "roll_call__id")


def _missing_records(student):
    from boarding.models import Absence

    return Absence.objects.filter(student=student).select_related("house").order_by("opened_at")


def _invitations(student):
    return GuardianInvite.objects.filter(students=student).order_by("created_at")


def _sign_up_requests(student):
    return ParentSignupRequest.objects.filter(student=student).order_by("created_at")


def _change_log(student):
    """Activity log entries about the student (IDs and short descriptions, as staff see them)."""
    return ActivityLog.objects.filter(school=student.school, target_type="student", target_id=student.id) \
        .order_by("created_at")


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
        "support": [{
            "status": c.get_status_display(), "term": c.term.name if c.term else "", "reasons": [
                r.get("label", "") for r in c.reasons], "note": c.note, "support_plan": c.support_plan,
            "review_date": _iso(c.review_date), "marked_by": c.created_by_name, "marked": _iso(c.created_at),
            "closed": _iso(c.closed_at), "closing_note": c.closing_note,
        } for c in student.support_concerns.select_related("term").order_by("created_at")],
        "discipline": [{
            "date": _iso(i.date), "category": i.get_category_display(), "severity": i.get_severity_display(),
            "what_happened": i.description, "action": i.get_action_display(), "action_detail": i.action_detail,
            "staff_notes": i.staff_notes, "shared_with_parents": i.shared_with_parents,
            "recorded_by": i.recorded_by_name,
        } for i in student.discipline_incidents.order_by("date", "id")],
        "merits": [{
            "date": _iso(m.date), "for": m.get_category_display(), "points": m.points, "reason": m.reason,
            "shared_with_parents": m.shared_with_parents, "given_by": m.awarded_by_name,
        } for m in student.merits.order_by("date", "id")],
        "student_account": _account(student),
        "homework": [{
            "due": _iso(r.assignment.due_date), "subject": r.assignment.subject.name, "homework": r.assignment.title,
            "recorded_as": r.get_status_display() if r.status else "", "mark": r.mark, "comment": r.comment,
            "marked_done": _iso(r.done_at), "answer": r.answer,
        } for r in _homework(student)],
        "clubs": {
            "memberships": [{"club": m.club.name, "joined": _iso(m.joined_on), "role": m.role}
                            for m in _club_memberships(student)],
            "registers": [{"club": a.session.club.name, "date": _iso(a.session.date), "status": a.get_status_display()}
                          for a in _club_marks(student)],
            "picked_for": [{"club": f.club.name, "date": _iso(f.date), "against": f.opponent} for f in _club_fixtures(student)],
        },
        "boarding": {
            "bed": _bed(student),
            "roll_call_marks": [{"date": _iso(e.roll_call.date), "session": e.roll_call.get_session_display(),
                                 "house": e.roll_call.house.name, "status": e.get_status_display(), "note": e.note}
                                for e in _roll_call_marks(student)],
            "missing_records": [{"house": a.house.name, "since": _iso(a.opened_at), "note": a.note,
                                 "status": a.get_status_display(), "resolution": a.get_resolution_display() if a.resolution else "",
                                 "resolved": _iso(a.resolved_at), "resolved_by": a.resolved_by_name,
                                 "resolution_note": a.resolution_note} for a in _missing_records(student)],
            "leave": [{"kind": x.get_kind_display(), "leaving": _iso(x.leaving_at), "returning": _iso(x.returning_at),
                       "reason": x.reason, "collected_by": x.collected_by, "status": x.get_status_display(),
                       "decision_note": x.decision_note} for x in student.leave_requests.order_by("leaving_at")],
            "sick_bay": [{"checked_in": _iso(v.checked_in_at), "complaint": v.complaint, "treatment": v.treatment,
                          "checked_out": _iso(v.checked_out_at), "outcome": v.get_outcome_display()}
                         for v in student.sick_bay_visits.order_by("checked_in_at")],
        },
        "admissions_applications": _applications(student),
        "parent_invitations": [{"name": i.name, "email": i.email, "sent": _iso(i.created_at),
                                "accepted": _iso(i.accepted_at)} for i in _invitations(student)],
        "parent_sign_up_requests": [{"name": r.name, "email": r.email, "phone": r.phone,
                                     "relationship": r.relationship, "admission_number_given": r.admission_number,
                                     "status": r.get_status_display(), "sent": _iso(r.created_at)}
                                    for r in _sign_up_requests(student)],
        "change_log": [{"when": _iso(e.created_at), "by": e.actor_name, "action": e.action, "what": e.summary}
                       for e in _change_log(student)],
        "conversations_about_the_student": [{
            "sent": _iso(m.created_at), "from": display_name(m.sender) if m.sender else "Removed", "message": m.body,
        } for m in _messages_about(student)],
    }


def _applications(student):
    from admissions.services import application_row, applications_about

    return [application_row(a) for a in applications_about(student).order_by("created_at")]


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
    # Admissions applications for the child: what the family typed in, and the school's notes on it.
    from admissions.services import applications_about

    counts["applications_deleted"] = applications_about(student).delete()[0]
    counts["support_concerns_deleted"] = student.support_concerns.all().delete()[0]
    counts["discipline_records_deleted"] = student.discipline_incidents.all().delete()[0]
    counts["merits_deleted"] = student.merits.all().delete()[0]
    counts["student_account_deleted"] = 1 if _delete_account(student) else 0
    counts["homework_records_deleted"] = student.homework_records.all().delete()[0]
    counts["club_records_deleted"] = (student.club_memberships.all().delete()[0]
                                      + student.club_attendance.all().delete()[0])
    student.fixtures.clear()
    counts["boarding_records_deleted"] = (student.leave_requests.all().delete()[0]
                                          + student.sick_bay_visits.all().delete()[0]
                                          + student.roll_call_entries.all().delete()[0])
    from boarding.models import Absence
    from boarding.services import release_boarders

    release_boarders([student.id], "left_school", actor)
    counts["boarding_records_deleted"] += Absence.objects.filter(student=student).delete()[0]

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


def _club_memberships(student):
    return student.club_memberships.select_related("club").order_by("joined_on", "id")


def _club_marks(student):
    return student.club_attendance.select_related("session__club").order_by("session__date", "id")


def _club_fixtures(student):
    return student.fixtures.select_related("club").order_by("date", "id")


def _homework(student):
    return student.homework_records.select_related("assignment__subject").order_by("assignment__due_date", "id")


def _account(student):
    from studentaccounts.models import StudentAccount

    account = StudentAccount.objects.filter(student=student).select_related("user").first()
    if account is None:
        return None
    return {"username": account.user.username, "made": _iso(account.created_at), "made_by": account.created_by_name,
            "last_signed_in": _iso(account.user.last_login), "turned_on": account.user.is_active}


def _delete_account(student):
    from studentaccounts.models import StudentAccount

    return StudentAccount.objects.filter(student=student).delete()[0] > 0
