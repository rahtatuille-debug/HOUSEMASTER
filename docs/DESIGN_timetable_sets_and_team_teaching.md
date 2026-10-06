# Design note: sets across classes, and team teaching

Status: note only (F). Nothing here is built, except the per-block change for double lessons noted at the end.

## Today

- **Lessons belong to one class.** Every lesson is `(school_class, subject, teacher, room, day, period)`.
- **Electives.** Students who don't take an elective are simply not expected in that lesson
  (`timetable.services.student_lessons`). Two electives may share a slot when no student takes both; this is
  checked when placing a lesson and, since F-2, when options change.
- **One teacher per lesson.**

## Gaps

1. **Sets across classes.** A maths set drawn from 10A, 10B and 10C is taught in one room at one time. Today it
   has to be entered as three lessons (one per class) with the same teacher and room, and the clash check refuses
   that: the teacher and the room would be double-booked.
2. **Team teaching.** Two teachers, or a teacher and an assistant, in one lesson. Only one can be named.
3. **Students in a set** are not recorded. Electives say who takes a subject, not which set they are in.

## Options

| | How | For | Against |
|---|---|---|---|
| A. Teaching group | `TeachingGroup(school, subject, name, classes M2M or students M2M)`; a lesson belongs to a class **or** a group; clashes are checked per student | Models sets properly; the teacher and room are booked once | Every lesson query (week views, today, parents) must resolve groups to students; the biggest change |
| B. Shared slot flag | Lessons in several classes with the same teacher, room and slot are allowed when marked as one "joint" lesson (`joint_key`) | Small; the clash check ignores rows with the same `joint_key` | Doesn't record who is in which set; editing one row must edit the others |
| C. Extra teachers | `Lesson.extra_teachers` M2M; teacher clash checks consider them | Small and independent of A/B | — |

## Recommendation

C now, if a school needs team teaching (small and safe). B as an interim for sets if a pilot school timetables
by sets. A only once sets matter for marks and reports too (set-based grade entry). [VERIFY with pilot schools]

## Double lessons (F, done in this fix)

A double lesson is already stored as two one-period lessons, each with its own teacher and room. The "Double
lesson" option on the timetable now lets the admin give the second period a different teacher or room when
adding it (frontend PR on `claude/fix-f-timetable`). No model change was needed.
