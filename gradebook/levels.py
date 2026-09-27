"""
Performance levels and grades shown next to percentages. Each school picks a
scale (in the setup wizard or Setup); percentages are still what's stored.

The 4-level scale is the standard CBC rubric and the 8-level one the KNEC
junior school scale. The others are the usual national or exam-board scales
for the systems a school can choose. Each band is (lowest percent, code,
name), highest first.
"""
SCALES = {
    "cbc4": [
        (80, "EE", "Exceeding Expectations"),
        (50, "ME", "Meeting Expectations"),
        (30, "AE", "Approaching Expectations"),
        (0, "BE", "Below Expectations"),
    ],
    "cbc8": [
        (90, "EE1", "Exceeding Expectations"),
        (75, "EE2", "Exceeding Expectations"),
        (58, "ME1", "Meeting Expectations"),
        (41, "ME2", "Meeting Expectations"),
        (31, "AE1", "Approaching Expectations"),
        (21, "AE2", "Approaching Expectations"),
        (11, "BE1", "Below Expectations"),
        (0, "BE2", "Below Expectations"),
    ],
    # KCSE (8-4-4) letter grades, with the commonly used mark ranges.
    "kcse": [
        (80, "A", "A (plain)"), (75, "A-", "A minus"), (70, "B+", "B plus"), (65, "B", "B (plain)"),
        (60, "B-", "B minus"), (55, "C+", "C plus"), (50, "C", "C (plain)"), (45, "C-", "C minus"),
        (40, "D+", "D plus"), (35, "D", "D (plain)"), (30, "D-", "D minus"), (0, "E", "E"),
    ],
    # Cambridge IGCSE letter grades (typical boundaries; exam boards set their own each series).
    "igcse": [
        (90, "A*", "A star"), (80, "A", "A"), (70, "B", "B"), (60, "C", "C"), (50, "D", "D"),
        (40, "E", "E"), (30, "F", "F"), (20, "G", "G"), (0, "U", "Ungraded"),
    ],
    # The 9 to 1 GCSE/IGCSE scale (typical boundaries).
    "igcse9": [
        (90, "9", "Grade 9"), (80, "8", "Grade 8"), (70, "7", "Grade 7"), (60, "6", "Grade 6"),
        (50, "5", "Grade 5"), (40, "4", "Grade 4"), (30, "3", "Grade 3"), (20, "2", "Grade 2"),
        (10, "1", "Grade 1"), (0, "U", "Ungraded"),
    ],
    # IB 1 to 7 (typical boundaries; the IB sets them per subject each session).
    "ib": [
        (80, "7", "Excellent"), (70, "6", "Very good"), (60, "5", "Good"), (50, "4", "Satisfactory"),
        (40, "3", "Mediocre"), (25, "2", "Poor"), (0, "1", "Very poor"),
    ],
    # American letter grades.
    "american": [
        (90, "A", "A"), (80, "B", "B"), (70, "C", "C"), (60, "D", "D"), (0, "F", "F"),
    ],
    "percent": [],
}

# How each scale is offered to schools, in the order shown.
SCALE_LABELS = {
    "cbc4": "CBC: 4 levels (EE, ME, AE, BE)",
    "cbc8": "CBC junior/senior school: 8 levels (EE1 to BE2)",
    "kcse": "KCSE letter grades (A to E)",
    "igcse": "IGCSE letter grades (A* to G)",
    "igcse9": "GCSE/IGCSE numbers (9 to 1)",
    "ib": "IB grades (7 to 1)",
    "american": "American letter grades (A to F)",
    "percent": "Percentages only",
}


def levels(scale):
    """The bands for a scale, for sending to the app: [{min, code, name}], highest first."""
    return [{"min": low, "code": code, "name": name} for low, code, name in SCALES.get(scale, [])]


def level_for(percent, scale):
    """The level code for a percentage (e.g. "ME"), or "" when there's no scale or no percentage."""
    if percent is None:
        return ""
    for low, code, _name in SCALES.get(scale, []):
        if percent >= low:
            return code
    return ""


def with_level(percent, scale, digits=0):
    """"72% · ME", or just "72%" for percentage-only schools."""
    if percent is None:
        return "—"
    text = f"{percent:.{digits}f}%"
    code = level_for(percent, scale)
    return f"{text} · {code}" if code else text


def levels_key(scale):
    """A one-line key for printed reports, e.g. "EE 80–100%, ME 50–79%, AE 30–49%, BE 0–29%"."""
    bands = SCALES.get(scale, [])
    tops = [100] + [low - 1 for low, _code, _name in bands[:-1]]
    return ", ".join(f"{code} {low}–{top}%" for (low, code, _name), top in zip(bands, tops))


def school_summary(school):
    """The school details every signed-in page needs: grading scale, words to use and country."""
    from students.presets import country, vocab

    from .systems import REPORT_EXTRAS, SUBJECT_FIELDS

    return {"id": school.id, "name": school.name, "grading_scale": school.grading_scale,
            "levels": levels(school.grading_scale), "education_system": school.education_system,
            "privacy_contact": school.privacy_contact,
            "setup_completed": school.setup_completed_at is not None,
            "vocab": vocab(school.education_system), "country": country(school.country),
            "report_extras": REPORT_EXTRAS.get(school.education_system, []),
            "subject_fields": SUBJECT_FIELDS.get(school.education_system, [])}
