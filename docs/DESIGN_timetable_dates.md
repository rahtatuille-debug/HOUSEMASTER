# Design note: timetables that change with dates

Status: note only (F). Nothing here is built.

## Today

- **One timetable.** There is a single weekly timetable per school: `Lesson(day, period)`, the same every week.
  It has no start or end date, no term, and no week A or week B.
- **Changes are immediate.** Changing a lesson changes it for every week, past and future. Nothing records which
  timetable applied on a given date; only the activity log says that a change happened.
- **"Today" screens.** The teacher home and the parents' view read today's weekday from this one timetable.

## What schools will ask for

1. **A new timetable from a date**, for example a new term starting on 12 January, without breaking this week.
2. **Fortnightly (week A / week B) timetables.**
3. **One-off changes:** a trip, exams or a cover lesson on one date.
4. **History:** which lesson a class had on a past date, for example to check against attendance.

## Options

| | How | For | Against |
|---|---|---|---|
| A. Timetable versions | `Timetable(school, starts_on, ends_on, name)`; `Lesson.timetable` FK. The version in force on a date is the latest `starts_on <= date`. Admins copy a version, edit it and publish it from a date | Covers 1 and 4; one more FK and a "which version" query | A data migration puts every existing lesson in one version starting at the school's first term; copying a version duplicates rows |
| B. Week A/B on top of A | `Lesson.week` in `{"", "A", "B"}` plus an anchor date on the version | Covers 2 | Every "today" query needs the week parity; the UI needs two grids |
| C. Date overrides | `LessonChange(date, lesson or slot, cancelled / replacement teacher / room / note)` | Covers 3 without touching the weekly plan; it is also where cover would live | Another table the "today" views must merge |
| D. Dated lessons | Every lesson becomes a dated event | Flexible | Explodes the row count; editing a weekly pattern becomes a bulk operation |

## Recommendation

A first, then C; B only when a school asks for it. Not D.

**A's migration**, when built:
- create one version per school, starting at the earliest term's start date;
- set `Lesson.timetable` on every lesson as a separate backfill command (dry run by default);
- add the NOT NULL constraint afterwards, with a pre-flight that counts lessons without a version.

**Open questions:**
- whether attendance should record the lesson it was taken in (today it is daily, not per lesson);
- how far back the history needs to go. [VERIFY with pilot schools]
