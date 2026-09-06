# Frontend handoff: display names and roles

Update the HouseMaster frontend to display people by their names and roles instead of their email addresses.

## Product rule

Emails are for authentication only: login, sign-up/invitations, and password reset. Do not show emails as a person's visible identity inside the application.

Show people as their name and role, for example: `Jaden Opil · Admin` or `Amina Otieno · Teacher`.

Never show an email such as `jadenopil@gmail.com` in normal in-app UI.

## Current-user API

`GET /api/me/` now returns:

```json
{
  "name": "Amina Otieno",
  "role": "teacher",
  "school": {
    "id": 1,
    "name": "Alpha Academy"
  }
}
```

Do not expect or display `email` from `/api/me/` in the normal app UI.

Use `name` as the visible identity, `role` for role labels/permissions, and `school.name` for school identity. Roles are `admin` and `teacher`; display them as `Admin` and `Teacher`.

Update all current-user UI: header, sidebar, profile menu, settings, welcome text, signed-in identity, announcement authoring, and activity/audit UI. Use `{currentUser.name} · {RoleLabel}`.

## Profile display-name update

Staff can update their own visible name with:

```text
PATCH /api/me/
```

```json
{
  "name": "Jaden Opil"
}
```

Add this to an existing profile/settings screen, or create a lightweight profile section.

Required field: `Display name` or `Full name`; required, 2–255 characters, trim whitespace.

After success, update global current-user state immediately and show: `Your display name has been updated.`

Suggested profile UI:

```text
Profile

Display name
[Jaden Opil__________________]

Role
Admin

School
HouseMaster Academy

[Save changes]
```

## Announcement author API

Announcement responses include:

```json
{
  "id": 42,
  "title": "Year 8 Student Reporting Date Notice",
  "body": "Please be advised that Year 8 students will report to school on the 8th of September due to ongoing renovations.",
  "audience": "all_staff",
  "status": "published",
  "created_by": 5,
  "created_by_name": "Jaden Opil",
  "created_by_role": "Admin",
  "created_at": "2026-09-06T19:58:43Z",
  "published_at": "2026-09-06T19:59:13Z",
  "archived_at": null
}
```

Update announcement cards, list rows, details, drawers, and admin views. Replace author email with:

```text
{created_by_name} · {created_by_role}
```

Example:

```text
AUTHOR
Jaden Opil · Admin
```

If `created_by_name` is null/unavailable, show `School staff` or `School administrator`. Never fall back to an email address and never expose numeric `created_by` IDs.

## Central role helper and types

```ts
function getRoleLabel(role: string): string {
  if (role === "admin") return "Admin";
  if (role === "teacher") return "Teacher";
  return "Staff";
}

type UserRole = "admin" | "teacher";

interface CurrentUser {
  name: string;
  role: UserRole;
  school: {
    id: number;
    name: string;
  };
}

interface Announcement {
  id: number;
  school: number;
  title: string;
  body: string;
  audience: "all_staff" | "all_parents" | "year_group" | "school_class";
  year_group: number | null;
  school_class: number | null;
  status: "draft" | "published" | "archived";
  created_by: number | null;
  created_by_name: string | null;
  created_by_role: string | null;
  created_at: string;
  published_at: string | null;
  archived_at: string | null;
}
```

## Invitations

For staff-invitation/onboarding screens, collect both `Full name` and `Email address`. The name is the visible profile identity; email is only a login credential. New invite acceptances automatically inherit the invitation name as the account display name.

## Acceptance criteria

- Header/sidebar shows `{name} · {role}`, never email.
- Announcement author areas show `created_by_name · created_by_role`.
- The author display in the announcement UI reads `Jaden Opil · Admin`, not `jadenopil@gmail.com`.
- A user can update their own name with `PATCH /api/me/`.
- The new name updates across the app without refresh.
- Emails stay limited to login, invitations/sign-up, password reset, and account-security contexts.
- Update TypeScript types, API mappers, mocks, fixtures, and tests that still expect `me.email` or email-based announcement author fields.
