# Design: data-subject requests and retention (F-16)

Retention *periods* are for counsel to decide (audit report, section 7).
This covers the mechanism only.

**What already existed.** The audit's search missed it: `students/privacy.py`
already had an admin-only family export (an Excel workbook) and "remove
personal data" (admin-only, confirmed by typing the student's full name,
logged). This change fills the gaps in both and adds retention.

**1. Who can do it.** School admins only, for their own school's students:
the existing `IsSchoolAdmin` permission and school-scoped lookup (another
school's student is a 404). Teachers can't (403). These actions are admin
actions, and admins don't go through the approvals workflow (it exists for
teachers' changes), so nothing is routed through approvals. Removal still
requires typing the full name, because it can't be undone.

**2. What the export contains.** Everything held about the child and their
parents: profile, parents and their contact details, grades, attendance
(with notes), every report (with the internal summary), per-subject teacher
comments, the parents' messages, and every conversation about the child.
It stays an Excel workbook for handing to a family, and is also available
as JSON (`?format=json`) for checking and machine use. Each export is
logged in the activity log.

**3. Anonymise, not delete.** Grades and attendance statuses stay, under
the name "Removed student", so class averages and other children's history
don't change. Everything that identifies the child goes: names, admission
number, date of birth, gender, nationality, house, mode of learning,
admission date, health notes, photo, attendance notes, report comments and
summaries (whole reports are deleted), and parent sign-up requests that
named the child.

**4. Free text that mentions the child.** Names are replaced with "Removed
student" in the activity log, teachers' pending requests, per-subject
comments and the messages of conversations about the child. First names are
replaced only as whole words and only in text about this child (their
subject comments and their conversations), so another pupil called Grace
isn't touched elsewhere. A name typed in a shortened or misspelled form
can't be found reliably; that is the residual risk.

**5. The activity log.** Summaries stay readable sentences (the admins
rely on them), rather than being rewritten into structured references at
all 96 call sites. Every entry already records the target's type and ID in
structured fields, and removal scrubs the names. Rows about children
removed before this change were already scrubbed by the earlier removal
code; there is no way to find names that are no longer stored, so no
one-off back-fill is possible or needed.

**6. What is kept, and why.** The activity-log entries themselves
(scrubbed), because they are the school's audit trail; grades and
attendance statuses (anonymous), for the school's statistics; parents who
have other children at the school keep their account and only lose the
link. Django's own admin history (`LogEntry`) can hold an object's name if
a superuser edited it in the admin; that is outside the app's removal.

**7. Retention.** `manage.py apply_retention` anonymises students who have
been inactive (left or graduated) for longer than
`RETENTION_INACTIVE_STUDENT_YEARS`. It is **off** until that is set, and a
dry run unless `--apply` is given, so nothing is removed until a person
chooses a period and runs it on purpose. On the free tier (no shell) the
owner can add `python manage.py apply_retention --apply` to the build
command once counsel has set the period.
