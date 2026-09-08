# Frontend handoff: Guardian Students and Communications

Extend the existing guardian/parent account experience. Guardians already have Profile and Messages. Add **Students** and **Communications** navigation items.

Guardians are a separate identity from school staff. Do not use staff endpoints such as `/api/students/`, `/api/grades/`, or `/api/reports/` for guardian pages.

## Guardian identity

Use:

```text
GET /api/guardian-me/
```

Response:

```json
{
  "name": "Grace Otieno",
  "school": {"id": 1, "name": "Alpha Academy"},
  "students": [
    {
      "id": 12,
      "first_name": "Amina",
      "last_name": "Otieno",
      "school_class": 4,
      "school_class_name": "Year 8 — 8A",
      "house": "Blue",
      "enrolled_on": null,
      "is_active": true
    }
  ]
}
```

Display guardians by `name`, never their email address. Name update:

```text
PATCH /api/guardian-me/
{"name": "Grace M. Otieno"}
```

## Students navigation and list

Add a `Students` navigation item for guardian users. It uses:

```text
GET /api/guardian-students/
```

Show each returned child as a card with their name, class, house when available, and a `View progress` action. The API returns only formally linked children: never include search or arbitrary student-ID entry.

Empty state:

```text
No students are linked to this account yet. Please contact the school office.
```

## Student detail, grades, and reports

Student detail:

```text
GET /api/guardian-students/:id/
```

Grades:

```text
GET /api/guardian-students/:id/grades/
GET /api/guardian-students/:id/grades/?term=<term_id>
```

Grade item:

```json
{
  "id": 9,
  "subject": 1,
  "subject_name": "Mathematics",
  "term": 2,
  "term_name": "Term 1 2026",
  "score": "86.00",
  "max_score": "100.00",
  "recorded_at": "2026-09-08T08:00:00Z"
}
```

Reports / grade reviews:

```text
GET /api/guardian-students/:id/reports/
```

Report item:

```json
{
  "id": 3,
  "term": 2,
  "term_name": "Term 1 2026",
  "progress_summary": "Strong progress.",
  "report_comment": "Well done.",
  "status": "finalized",
  "generated_at": "2026-09-08T08:00:00Z",
  "edited_at": "2026-09-08T08:00:00Z"
}
```

Build child detail with `Overview`, `Grades`, and `Reports` tabs/sections. This is read-only: no edit, generation, publish, or data-entry controls. Treat 404 as: `This student is unavailable.`

## Communications navigation

Add a `Communications` navigation item for guardians:

```text
GET /api/announcements/
```

It returns only published notices relevant to the guardian:

- `all_parents`
- notices matching a linked child's year group
- notices matching a linked child's class

It excludes staff-only, draft, archived, and unrelated year-group/class announcements.

Render title, body, audience, published date, and author. Show author as `created_by_name · created_by_role`, never email.

Guardian Communications is read-only. Do not show create, manual draft, AI draft, edit, publish, or archive controls. Direct conversations stay under the existing Messages section.

## Acceptance criteria

- Guardian navigation includes Students and Communications.
- Students lists only children from `/api/guardian-students/`.
- Child detail shows read-only grades and reports.
- Parent communications only renders API-returned notices and has no staff authoring controls.
- People use name/role rather than email.
- Loading, empty, 403, and 404 states are handled.

