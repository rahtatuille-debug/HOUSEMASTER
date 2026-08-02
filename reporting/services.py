"""
Core generation logic for Phase 2 — turns a student's grades + attendance for a
term into an AI-generated progress summary and draft report comment.

Uses the Gemini API directly (via the `google-genai` package). Requires
GEMINI_API_KEY to be set in the environment.
"""
import os

from gradebook.models import Grade
from attendance.models import AttendanceRecord
from .models import StudentReport

MODEL = "gemini-2.5-flash"

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

    grade_lines = [
        f"- {g.subject.name}: {g.score}/{g.max_score}" for g in grades
    ] or ["- No grades recorded this term."]

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
        f"Student: {student.first_name} {student.last_name}\n"
        f"Term: {term.name}\n\n"
        f"Grades:\n" + "\n".join(grade_lines) + "\n\n"
        f"Attendance:\n{attendance_summary}"
    )


def _build_prompt(student, term, tone):
    context = _build_student_context(student, term)
    tone_instruction = TONE_GUIDANCE.get(tone, TONE_GUIDANCE["formal"])

    return f"""You are helping a teacher prepare a student progress report from the data below.

{context}

Write two things, clearly separated by the exact header lines shown below (no extra markdown, no additional headers):

SUMMARY:
A 2-4 sentence progress summary covering trends, strengths, and areas to watch. Written for internal school records — this is not shown directly to parents.

COMMENT:
A 2-4 sentence draft report comment written directly to the student/parent, in this tone: {tone_instruction}
It should be specific to the data above, not generic. Do not invent facts not present in the data."""


def _parse_response(text):
    """Split the model's SUMMARY:/COMMENT: response into two strings."""
    summary, comment = "", ""
    if "SUMMARY:" in text and "COMMENT:" in text:
        summary_part, comment_part = text.split("COMMENT:", 1)
        summary = summary_part.split("SUMMARY:", 1)[1].strip()
        comment = comment_part.strip()
    else:
        # Fallback: if the model didn't follow the format, put everything in summary
        summary = text.strip()
        comment = ""
    return summary, comment


def generate_report(student, term):
    """
    Generate (or regenerate) a StudentReport for this student/term via the AI,
    respecting the student's school's configured report_tone. Returns the
    StudentReport instance (created or updated).
    """
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Set it in your environment before generating reports."
        )

    tone = student.school.report_tone
    prompt = _build_prompt(student, term, tone)

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(model=MODEL, contents=prompt)
    text = response.text
    summary, comment = _parse_response(text)

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
