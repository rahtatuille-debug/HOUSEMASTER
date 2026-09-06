# HouseMaster — Phase 1 + 2 Scaffold

Django + DRF backend for HouseMaster's Phase 1 modules (student records, gradebook,
attendance, Excel import) plus Phase 2 (AI-generated reporting).

## Setup

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python manage.py migrate
./venv/bin/python manage.py createsuperuser   # for /admin/
./venv/bin/python manage.py runserver
```

Admin: http://localhost:8000/admin/
API root: http://localhost:8000/api/ (schools, school-classes, students, subjects,
terms, grades, attendance, announcements)

## Apps

- **students** — `School`, `YearGroup`, `SchoolClass`, `Student`. The spine everything
  else hangs off. Also owns the Excel import command.
- **gradebook** — `Subject`, `Term`, `Grade`.
- **attendance** — `AttendanceRecord` (present/absent/late/excused).
- **reporting** — `StudentReport` model plus a generation service. Pulls a
  student's `Grade`/`AttendanceRecord` data for a term, calls the Gemini API,
  and stores an AI-generated progress summary + draft report comment respecting
  the school's `report_tone`.
- **communications** — admin-authored, one-way `Announcement`s. They can
  target all staff, all parents, a year group, or a class; use drafts plus the
  publish/archive actions to control their lifecycle.

## Announcements

Only school admins can create, edit, publish, or archive announcements. Create
a draft with `POST /api/announcements/`, then publish it with
`POST /api/announcements/<id>/publish/`. Published announcements can be retired
with `POST /api/announcements/<id>/archive/`.

```json
{
  "title": "Year 7 trip consent forms",
  "body": "Please return signed consent forms by Friday.",
  "audience": "school_class",
  "school_class": 12
}
```

The API also accepts `all_staff`, `all_parents`, and `year_group` audiences
(`year_group` requires a `year_group` ID). At this stage the app has staff
accounts only, so non-admin staff can see published `all_staff` notices.
Parent accounts and teacher-to-class memberships will be needed before the
other delivery audiences can be shown to their recipients.

Admins and teachers can generate editable wording from a short brief with
`POST /api/announcements/generate-text/`. This does not create or publish an
announcement. It needs `GEMINI_API_KEY`, like report generation:

```json
{
  "summary": "Tell staff that school closes at 12:30 on Friday for staff training.",
  "audience": "all_staff"
}
```

The response contains a suggested `title` and `body`; an admin must review it,
save it as a draft, and publish it separately.

## Importing a school's Excel workbook

Per the agreed template (one workbook, three sheets):

- **Students**: `id, first_name, last_name, class, house`
- **Grades**: `student_id, subject, term, score, max_score`
- **Attendance**: `student_id, date, status, notes`

```bash
./venv/bin/python manage.py import_school_workbook path/to/workbook.xlsx --school "School Name"
```

- Creates the `School` if it doesn't exist.
- `student_id` in Grades/Attendance must match a student's `id` from the Students
  sheet (stored as `external_id`) — rows for unknown students are skipped, not
  fatal to the whole import.
- Re-running the import with the same workbook updates existing records
  (`update_or_create`) rather than duplicating them.

## Generating reports (Phase 2)

Requires `GEMINI_API_KEY` set in the environment.

```bash
export GEMINI_API_KEY=...
```

Via the API:

```bash
curl -X POST http://localhost:8000/api/reports/generate/ \
  -H "Content-Type: application/json" \
  -d '{"student": 1, "term": 1}'
```

This pulls the student's grades and attendance for that term, sends them to
Gemini along with the school's configured `report_tone`, and stores the result
as a `StudentReport` (or updates the existing one for that student/term).
Returns 503 with a clear message if `GEMINI_API_KEY` isn't set, rather than
crashing.

Teachers review/edit the `report_comment` before finalizing — `StudentReport`
supports normal CRUD (`PATCH /api/reports/<id>/`) for that, and `status` moves
from `draft` → `reviewed` → `finalized` as they work through it.

## Design notes carried over from the plan

- Report comment tone (`School.report_tone`) is configurable per school, not per
  teacher, for v1.
- Data entry is Excel-first for Phase 1; native in-app data entry can replace this
  later without changing the underlying models.
- Timetabling, communication, behavior/pastoral tracking, and admissions are later
  phases and have no models yet.

## Next steps

1. Add auth (JWT, matching the pattern used in Cliniq/HMS) and school-scoped
   permissions so one school's data isn't visible to another's API calls.
2. Add DRF filtering/pagination as data volume grows.
3. Stand up Postgres via Neon and point `DATABASES` at it instead of SQLite.
4. Frontend: a teacher-facing screen to trigger generation and review/edit
   `StudentReport`s (draft → reviewed → finalized).
