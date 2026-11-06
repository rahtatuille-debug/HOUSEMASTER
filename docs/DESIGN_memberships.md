# One login, several schools

**Status:** built.

A person can be staff at one school, staff at another, and a parent at a third (or a teacher and a parent at the
same school) with one email and one password. Each place is a **membership**: a staff `Profile` or a parent
`Guardian`, at most one of each per school.

## How it works

- `Profile.user` and `Guardian.user` are foreign keys (they were one-to-one). `user.profile` and `user.guardian`
  still exist: `accounts/memberships.py` makes them the membership the session is acting as, so the views did not
  change.
- Every token carries the membership in the `mem` claim (`"staff:12"`, `"parent:7"`). `VersionedJWTAuthentication`
  sets it as the request's profile **or** guardian, never both, so a teacher-parent's parent session is refused by
  staff endpoints and the other way round. Tokens from before this change carry no claim and use the login's only
  membership; their next refresh adds it.
- Signing in starts where the person was last (`UserSecurity.last_membership`), else their first staff school,
  else their first parent account.
- `GET /api/account/memberships/` lists them; `POST /api/account/switch/ {membership}` returns new tokens for
  another one. Both work whatever the current school's state (paused for billing, still being set up), so nobody
  is stuck at a school that is closed to them. `/api/me/` and `/api/guardian-me/` include `memberships` too.
- Conversations and calendar links are per school.

## Joining another school

An invite (staff or parent), an approved sign-up request, or registering a new school with an email that already
signs in asks for that account's **current password** instead of a new one (`accounts/joining.py`). The invite
preview says `has_account: true` so the page can ask for it. An admin is never told that an email is in use at
another school.

## Each school controls only its part

- **Deactivating** someone (staff or parent) sets that membership's `is_active`. The login stays open while it
  has another active membership. A session acting as the deactivated one ends at its next request (401). With no
  active membership left, the login itself is closed, as before.
- **Erasing a family** (`students/privacy.py`) deletes that school's parent account and that school's messages;
  the login is deleted only when nothing is left anywhere.

## Known limits

- One password and one email for all of a person's schools: a password reset sent by one school's admin changes
  how they sign in everywhere (the email goes to them, not to the admin).
- An access token issued for a membership stays valid for the rest of its lifetime (60 minutes) after a switch;
  it remains limited to that membership.
