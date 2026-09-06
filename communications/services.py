"""AI-assisted drafting for announcements. Generated text is never published automatically."""
import os

from reporting.services import MODEL, TONE_GUIDANCE


def _build_prompt(*, school, summary, audience_label, target_label=None):
    tone_instruction = TONE_GUIDANCE.get(school.report_tone, TONE_GUIDANCE["formal"])
    audience_context = audience_label
    if target_label:
        audience_context = f"{audience_label}: {target_label}"

    return f"""You are helping {school.name} prepare an official school announcement.

The administrator or teacher's brief is:
{summary}

Intended audience: {audience_context}
Writing style: {tone_instruction}

Write a clear, accurate, professional announcement based only on the brief. Do not invent dates, times, locations, policies, contacts, or other facts. Keep it concise unless the brief needs more detail. Do not use markdown, greetings such as 'Dear parents', or a signature.

Return exactly this format, with no extra headings:
TITLE:
<a concise title, at most 180 characters>
BODY:
<the complete announcement body>"""


def _parse_response(text):
    """Return a title/body pair even if the model misses the requested format."""
    text = (text or "").strip()
    if "TITLE:" in text and "BODY:" in text:
        title_part, body = text.split("BODY:", 1)
        title = title_part.split("TITLE:", 1)[1].strip()
        return title[:180], body.strip()

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return "", ""
    return lines[0][:180], "\n".join(lines[1:]).strip()


def generate_announcement_text(*, school, summary, audience_label, target_label=None):
    """Generate editable announcement text from a staff member's short brief."""
    from google import genai

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Set it in your environment before generating announcements."
        )

    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=MODEL,
        contents=_build_prompt(
            school=school,
            summary=summary,
            audience_label=audience_label,
            target_label=target_label,
        ),
    )
    return _parse_response(response.text)
