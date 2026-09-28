"""
AI-assisted drafting for announcements. Generated text is never published
automatically.

The brief is written by staff, so it may name pupils or parents. Before it
goes to the provider, the full names of the school's pupils and parents and
any email addresses are swapped for placeholders ([PERSON 1], [EMAIL 1]),
and the school's name is left out. The placeholders are swapped back once
the draft returns (docs/AI_DATA_FLOW.md). A first name on its own, or a
nickname, can't be recognised reliably and is not masked.
"""
import re
from reporting.ai import generate_text
from reporting.services import TONE_GUIDANCE
from students.presets import writing_context


def _build_prompt(*, school, summary, audience_label, target_label=None):
    tone_instruction = TONE_GUIDANCE.get(school.report_tone, TONE_GUIDANCE["formal"])
    audience_context = audience_label
    if target_label:
        audience_context = f"{audience_label}: {target_label}"

    return f"""You are helping a school prepare an official school announcement.

{writing_context(school)}

The administrator or teacher's brief is:
{summary}

Intended audience: {audience_context}
Writing style: {tone_instruction}

Placeholders such as [PERSON 1] or [EMAIL 1] stand for real names and addresses that have been withheld. Copy them exactly as written wherever you need them, and never guess what they stand for.

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


EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


def _known_full_names(school):
    """Full names (two words or more) of the school's pupils and parents, longest first."""
    from guardians.models import Guardian
    from students.models import Student

    names = {f"{first} {last}".strip() for first, last in
             Student.objects.filter(school=school).values_list("first_name", "last_name")}
    names |= {name.strip() for name in Guardian.objects.filter(school=school).values_list("display_name", flat=True)}
    return sorted((n for n in names if len(n.split()) >= 2), key=len, reverse=True)


def mask_personal_details(text, school):
    """Swap known full names and email addresses for placeholders. Returns (masked text, placeholder map)."""
    mapping = {}
    seen = {}

    def placeholder(kind, original):
        key = (kind, original.lower())
        if key not in seen:
            seen[key] = f"[{kind} {sum(1 for k in seen if k[0] == kind) + 1}]"
            mapping[seen[key]] = original
        return seen[key]

    text = EMAIL_RE.sub(lambda m: placeholder("EMAIL", m.group(0)), text)
    names = _known_full_names(school)
    if names:
        pattern = re.compile(r"\b(" + "|".join(re.escape(n) for n in names) + r")\b", re.IGNORECASE)
        text = pattern.sub(lambda m: placeholder("PERSON", m.group(0)), text)
    return text, mapping


def restore_personal_details(text, mapping):
    for key, original in mapping.items():
        text = text.replace(key, original)
    return text


def generate_announcement_text(*, school, summary, audience_label, target_label=None):
    """Generate editable announcement text from a staff member's short brief."""
    masked, mapping = mask_personal_details(summary, school)
    text = generate_text(
        _build_prompt(school=school, summary=masked, audience_label=audience_label, target_label=target_label),
        missing_key_message="GEMINI_API_KEY is not set. Set it in your environment before generating announcements.",
    )
    title, body = _parse_response(text)
    return restore_personal_details(title, mapping)[:180], restore_personal_details(body, mapping)
