# HouseMaster handoff — work completed yesterday

## Repository state

- Branch: `master`
- Remote: `origin/master`
- Latest commit: `fdd14b5 Name display fix`
- The repository was reset to its latest committed state before this handoff was written.

Key commits, newest first:

```text
fdd14b5 Name display fix
2dafd7a AI Generated announcements
3d15970 Changes
9923c2d Major changes
```


## Summary

Yesterday's work delivered the first backend slice of Communications: school-scoped, one-way announcements; optional AI text generation; and a shift from email-based in-app identity to names and roles.

No frontend application source was changed in this repository. Frontend implementation guidance was added for the separate frontend agent.

## 1. Announcements backend

New Django app:

```text
communications/
```

It is registered in `INSTALLED_APPS` and exposed through the DRF router.

Base endpoint:

```text
/api/announcements/
```

Announcement fields:

```text
id, school, title, body, audience, year_group, school_class, status,
created_by, created_by_name, created_by_role, created_at, published_at, archived_at
```

Audiences:

```text
all_staff
all_parents
year_group
school_class
```

Lifecycle:

```text
draft → published → archived
```

- Creation produces a draft.
- Only drafts can be edited.
- Only drafts can be published.
- Only published announcements can be archived.
- There is no delete endpoint.

API endpoints:

```text
GET    /api/announcements/
GET    /api/announcements/:id/
POST   /api/announcements/
PATCH  /api/announcements/:id/
POST   /api/announcements/:id/publish/
POST   /api/announcements/:id/archive/
POST   /api/announcements/generate-text/
```

Supported filters: `status`, `audience`, `year_group`, and `school_class`.

Example manual draft:

```json
{
  "title": "Staff meeting",
  "body": "The staff meeting starts at 3pm in the library.",
  "audience": "all_staff"
}
```

Validation:

- `year_group` audience requires `year_group` and no `school_class`.
- `school_class` audience requires `school_class` and no `year_group`.
- `all_staff` and `all_parents` cannot include either target.
- Target classes/year groups must belong to the user's school.

### Current permissions — important

The committed backend currently has this permission model:

- Admins can create, edit, publish, archive, and see every announcement in their school.
- Teachers can read only published `all_staff` announcements and can use AI generation.
- Teachers cannot currently create manual announcement records: `POST /api/announcements/` is admin-only in committed code.

The later product requirement is that teachers must draft manually and with AI, while admins publish. A local implementation of that permission change was discarded when the repository was reset. It remains outstanding.

Recommended follow-up permission model:

- Teachers can create and edit only their own drafts.
- Teachers can see published all-staff notices plus their own drafts.
- Teachers cannot publish or archive.
- Admins can see, review, publish, and archive all school drafts.

## 2. AI-assisted announcement drafting

Endpoint:

```text
POST /api/announcements/generate-text/
```

Example request:

```json
{
  "summary": "Tell staff that school closes at 12:30 on Friday for staff training.",
  "audience": "all_staff"
}
```

Optional context fields: `audience`, `year_group`, and `school_class`.

Example response:

```json
{
  "title": "Early Closure for Staff Training",
  "body": "Please note that the school will close at 12:30 p.m. on Friday to allow for scheduled staff training. Please make the necessary arrangements."
}
```

Generation uses Gemini and `GEMINI_API_KEY`, with the school's configured tone as guidance. It returns editable text only; it never saves, sends, or publishes an announcement. It returns HTTP 503 when the API key is unavailable.

## 3. Names and roles instead of email addresses

Staff profiles now include `display_name`.

Migration added:

```text
accounts/migrations/0006_profile_display_name.py
```

Identity changes:

- `GET /api/me/` returns `name`, `role`, and `school`; normal app identity no longer uses email.
- Staff can update their displayed name:

```text
PATCH /api/me/
```

```json
{ "name": "Jaden Opil" }
```

- Accepted invitations copy the invitation name to the staff display name.
- Announcement payloads include `created_by_name` and `created_by_role`.
- The backend does not fall back to email as a display name. Missing names fall back to the role.

Example author output:

```json
{
  "created_by_name": "Jaden Opil",
  "created_by_role": "Admin"
}
```

Frontend display:

```text
Jaden Opil · Admin
```

Never display a login email in normal in-app UI.

## 4. Frontend guidance

Read this committed file before frontend changes:

```text
FRONTEND_NAME_AND_ROLE_HANDOFF.md
```

It contains API, type, UI, and acceptance guidance for names, roles, author displays, and profile updates.

The teacher manual-draft frontend brief was not committed and was removed by the reset. Recreate it after teacher-draft permissions are restored on the backend.

## 5. Verification

Focused tests were added for:

- Tenant isolation and cross-school target rejection.
- Admin announcement lifecycle.
- Audience validation.
- Teacher visibility of published all-staff notices.
- AI generation and missing Gemini configuration.
- Announcement author name/role output.
- `/api/me/` display-name updates.

`manage.py check` passed using a local SQLite override. The default Neon database host was not resolvable from the development sandbox; use a `DATABASE_URL=sqlite:...` override for local tests when necessary.

## 6. Recommended next steps

1. Restore teacher manual-draft permissions and add tests.
2. Give teachers and admins both `Write manually` and `Draft with AI` frontend paths.
3. Update frontend users/authors to use names and roles, never email.
4. Add parent accounts, parent-student links, and teacher-class/course membership before claiming delivery to parent/class/year-group audiences.
5. Then build recipient resolution, inboxes, delivery, direct messages, class/course broadcasts, and emergency alerts.

