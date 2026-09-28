# Security notes: accepted risks and why

Decisions where a small risk was kept on purpose, so the next person knows
it was a choice and not an oversight.

## "An account with this email already exists" on sign-up (F-12)

**What:** the public "register your school" form and the invite-accept
forms say so when the email is already in use. Someone can use that to
check whether an address has a HouseMaster account.

**Why it stays:** removing the message properly needs an email-verification
sign-up flow (the account is only created after the owner clicks a link),
which is a bigger change than this pass. Without the message, people who
already have an account would be stuck.

**How it's limited:** registration is limited to 5 per hour per IP address
and 3 per day per email address, and invite acceptance to 60 per hour per
IP (accounts/throttles.py). Once `DRF_NUM_PROXIES` is set, a spoofed
`X-Forwarded-For` header can't get round the per-IP limits, and the
per-email limit ignores the IP entirely. Login and password reset give the
same answer whether or not the account exists.

**Revisit:** when adding email verification to sign-up.

## Invites don't reveal accounts at other schools (F-12)

Creating a staff or parent invite only checks the admin's own school: an
address with an account at another school is invited exactly like an
unknown address (same 201 response), and acceptance is refused later, when
only the owner of that address sees why. Same-school duplicates still get
the helpful "already has an account" / "pending invite" messages.

Invite emails are limited to 100 per hour per admin and 5 per day per
recipient address across all schools, so invites can't be used to flood
someone's inbox. Reading and cancelling invites aren't limited.

The bulk staff import creates invites through its own path and is not
covered by these two limits. It is admin-only; limiting it is left as a
follow-up.

## One school per parent account

An email address can only belong to one account, and a parent account
belongs to one school. A parent with children at two HouseMaster schools
therefore can't have both on one login, and the second school's invite is
refused. This needs a product decision (one login linked to several
schools) rather than a security fix.

## Tokens in the browser (F-15)

Login tokens are kept in `localStorage`, where any script running on the
page could read them. There is no known way to inject a script today (no
raw HTML is rendered), refresh tokens now last 3 days and rotate on every
use, and a Content-Security-Policy is being introduced (report-only first).
Moving the refresh token to an httpOnly cookie is designed in
[DESIGN_httpOnly_refresh.md](DESIGN_httpOnly_refresh.md) but needs a custom
domain first.
