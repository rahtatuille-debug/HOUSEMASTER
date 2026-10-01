"""
Ranking students, the same way on every screen, export and report card.

- Higher is better. Tied students share a position and the next one skips
  (1, 2, 2, 4): "standard competition" ranking.
- 8-4-4 ranks by mean KCSE points, then average mark (the KCSE rule, as
  on its report card). Other curricula rank by average mark.
- CBC doesn't rank learners, so CBC students get no positions at all.
- Students are only ever ranked against others in the same curriculum.
"""
from gradebook.levels import level_for
from gradebook.systems import KCSE_POINTS, mean_grade

UNRANKED = {"cbc"}


def effective_system(system, scale):
    """The curriculum to rank by: a section with none set but graded on CBC levels counts as CBC."""
    if not system and (scale or "").startswith("cbc"):
        return "cbc"
    return system


def positions(scores):
    """{key: score or None} -> {key: position}. Scores are tuples compared highest first; None isn't ranked."""
    ordered = sorted((s for s in scores.values() if s is not None), reverse=True)
    first = {}
    for index, score in enumerate(ordered):
        first.setdefault(score, index + 1)
    return {key: first[score] for key, score in scores.items() if score is not None}


def overall_score(system, percents):
    """A student's standing for ranking from their subject percentages this term, or None."""
    values = [p for p in percents if p is not None]
    if not values or system in UNRANKED:
        return None
    average = sum(values) / len(values)
    if system == "844":
        points = [KCSE_POINTS[level_for(p, "kcse")] for p in values]
        return (round(sum(points) / len(points), 3), round(average, 3))
    return (round(average, 3),)


def subject_score(system, percent):
    if percent is None or system in UNRANKED:
        return None
    return (round(percent, 3),)


def kcse_totals(percents):
    """8-4-4 totals from subject percentages: total marks, total and mean points, mean grade."""
    values = [p for p in percents if p is not None]
    if not values:
        return {"total_marks": None, "total_points": None, "mean_points": None, "mean_grade": ""}
    points = [KCSE_POINTS[level_for(p, "kcse")] for p in values]
    mean = sum(points) / len(points)
    return {"total_marks": round(sum(values)), "total_points": sum(points),
            "mean_points": round(mean, 2), "mean_grade": mean_grade(mean)}
