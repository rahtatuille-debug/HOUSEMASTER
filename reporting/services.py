"""
Core generation logic for Phase 2 — turns a student's grades + attendance for a
term into an AI-generated progress summary and draft report comment.

Uses the Gemini API through reporting/ai.py, which bounds every call and
turns provider failures into AIUnavailable. Requires GEMINI_API_KEY.

No child's identity is ever sent: the prompt calls the student [STUDENT]
and carries only grades and attendance counts. The real first name is put
back locally once the text comes back (docs/AI_DATA_FLOW.md).
"""
import re

from gradebook.models import Grade
from attendance.models import AttendanceRecord
from gradebook.levels import level_for
from students.presets import student_section, words_for, writing_context

from .ai import generate_text
from .models import StudentReport

# What the model calls the student instead of their name.
PLACEHOLDER = "[STUDENT]"
# "[STUDENT]" in any case or spacing, or a bare upper-case STUDENT; never the ordinary word "student".
_PLACEHOLDER_RE = re.compile(r"(?i:\[\s*student\s*\])|\bSTUDENT\b")
_SENTENCE_START_RE = re.compile(r"(^|[.!?]\s+|\n\s*)the student")

TONE_GUIDANCE = {
    "formal": "Formal, professional register. Avoid contractions and casual phrasing.",
    "warm": "Warm and encouraging in tone, while still being honest about areas to improve.",
    "concise": "Concise and direct — short sentences, no filler, get straight to the point.",
}


def _build_student_context(student, term):
    """Assemble the raw data for one student/term into a compact text block for the prompt."""
    grades = Grade.objects.filter(student=student, term=term).select_related("subject")
    attendance = AttendanceRecord.objects.filter(
        student=student,
        date__gte=term.start_date if term.start_date else None,
        date__lte=term.end_date if term.end_date else None,
    ) if term.start_date and term.end_date else AttendanceRecord.objects.none()

    system, scale = student_section(student)
    words = words_for(student.school, system)

    def line(g):
        if g.max_score <= 0:
            # Can't happen any more (validation and a database constraint
            # prevent it), but never let such a mark vanish silently.
            return f"- {g.subject.name}: {g.score} (no valid maximum, so no percentage)"
        percent = float(g.score) / float(g.max_score) * 100
        level = level_for(percent, scale)
        return f"- {g.subject.name}: {g.score}/{g.max_score}" + (f" ({percent:.0f}%, {level})" if level else "")

    grade_lines = [line(g) for g in grades] or ["- No grades recorded this term."]

    total = attendance.count()
    if total:
        present = attendance.filter(status="present").count()
        absent = attendance.filter(status="absent").count()
        late = attendance.filter(status="late").count()
        excused = attendance.filter(status="excused").count()
        attendance_summary = (
            f"- {present}/{total} days present, {absent} absent, {late} late, {excused} excused."
        )
    else:
        attendance_summary = "- No attendance records for this term's date range."

    return (
        f"Student: {PLACEHOLDER}\n"
        f"{words['term']}: {term.name}\n\n"
        f"Grades:\n" + "\n".join(grade_lines) + "\n\n"
        f"Attendance:\n{attendance_summary}"
    )


def _build_prompt(student, term, tone):
    context = _build_student_context(student, term)
    tone_instruction = TONE_GUIDANCE.get(tone, TONE_GUIDANCE["formal"])

    return f"""You are helping a teacher prepare a student progress report from the data below.

{writing_context(student.school, student_section(student)[0])}

{context}

Write two things, clearly separated by the exact header lines shown below (no extra markdown, no additional headers):

SUMMARY:
A 2-4 sentence progress summary covering trends, strengths, and areas to watch. Written for internal school records — this is not shown directly to parents.

COMMENT:
A 2-4 sentence draft report comment written directly to the student/parent, in this tone: {tone_instruction}
It should be specific to the data above, not generic. Do not invent facts not present in the data.

The student's name is withheld. Wherever you would use their name, write exactly {PLACEHOLDER}. Do not guess a name, and do not assume their gender."""


class AIReplyUnusable(Exception):
    """The model answered, but not with a summary and a comment we can use."""


def _parse_response(text):
    """
    Split the model's SUMMARY:/COMMENT: response into two strings. An answer
    without both parts is refused rather than saved with a blank comment.
    """
    if "SUMMARY:" not in text or "COMMENT:" not in text:
        raise AIReplyUnusable("The answer didn't contain a summary and a comment.")
    summary_part, comment_part = text.split("COMMENT:", 1)
    summary = summary_part.split("SUMMARY:", 1)[1].strip()
    comment = comment_part.strip()
    if not summary or not comment:
        raise AIReplyUnusable("The answer had an empty summary or comment.")
    return summary, comment


def substitute_name(text, first_name):
    """Put the student's first name back where the model wrote the placeholder (or a variant of it)."""
    name = (first_name or "").strip()
    if name:
        return _PLACEHOLDER_RE.sub(name, text)
    text = _PLACEHOLDER_RE.sub("the student", text)
    return _SENTENCE_START_RE.sub(lambda m: m.group(1) + "The student", text)


def generate_report(student, term):
    """
    Generate (or regenerate) a StudentReport for this student/term via the AI,
    respecting the student's school's configured report_tone. Returns the
    StudentReport instance (created or updated).
    """
    tone = student.school.report_tone
    text = generate_text(
        _build_prompt(student, term, tone),
        missing_key_message="GEMINI_API_KEY is not set. Set it in your environment before generating reports.",
    )
    summary, comment = (substitute_name(part, student.first_name) for part in _parse_response(text))

    report, _ = StudentReport.objects.update_or_create(
        student=student,
        term=term,
        defaults={
            "progress_summary": summary,
            "report_comment": comment,
            "tone_used": tone,
            "status": "draft",
        },
    )
    return report
