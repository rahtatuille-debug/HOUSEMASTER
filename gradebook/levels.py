"""
CBC performance levels. Each school picks a scale in Setup; percentages are
still stored and shown, with the level alongside.

The 4-level scale is the standard CBC rubric. The 8-level scale is the KNEC
junior school scale (EE1 to BE2). Each band is (lowest percent, code, name),
highest first.
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
    "percent": [],
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
    """The school details every signed-in page needs, including its grading scale."""
    return {"id": school.id, "name": school.name, "grading_scale": school.grading_scale,
            "levels": levels(school.grading_scale)}
