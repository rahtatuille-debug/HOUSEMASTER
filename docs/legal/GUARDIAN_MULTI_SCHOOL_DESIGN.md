DRAFT — NOT LEGAL ADVICE — for review and adaptation by a qualified Kenyan data-protection advocate.

# Design note: a parent with children at two schools on HouseMaster

*A design note only; nothing is implemented. Legal points marked [VERIFY]
go to counsel (QUESTIONS_FOR_COUNSEL.md, question 14).*

## Today

- One email address belongs to one account (enforced by the database since
  F-13), and a parent account (`guardians.Guardian`) belongs to **one
  school**.
- So a parent whose children are at two HouseMaster schools can't be
  invited by the second school: the invite is refused when they try to
  accept it, and only they see why (docs/SECURITY_NOTES.md). They can't use
  HouseMaster for the second school at all, unless they use a different
  email address there.

## Options

### A. One identity, several school memberships

One login (`User`); one `Guardian` record **per school** (school, contact
details as that school holds them, children at that school). After signing
in, a parent with two memberships picks the school, or sees both in one
list with a school switcher.

- **Migration:** make the one-to-one link between `User` and `Guardian`
  a foreign key, so a user can have several guardian rows; unique on (user,
  school). Existing data needs no change (every user has one row). Every
  place that reads `user.guardian` (permissions, messaging contacts,
  notifications, scoping) must take a school: a large, careful change,
  with the isolation tests extended to users belonging to two schools.
- **Privacy:** each school stays the controller of its own membership
  record and sees only its own children and contact details; neither
  school learns that the parent uses the other. But the **login** (email,
  password, sessions) is shared: who controls it? Possibly HouseMaster as
  controller for the identity [VERIFY]. A password reset or deactivation by
  one school would affect access to the other: deactivation must become
  per membership.
- **Risk:** a bug in the school switch could show one school's data in the
  other's context. It's the tenant-isolation risk again, in a new place.

### B. Linked accounts

Two separate accounts (different logins), which the parent can link so that
signing in to one offers a switch to the other.

- **Migration:** small (a link table); isolation unchanged.
- **Privacy:** the schools stay fully separate; the link is the parent's own
  choice, held by HouseMaster [VERIFY: as controller].
- **Downside:** two email addresses or a plus-address; two passwords.

### C. Separate accounts per school (status quo, but allowed)

Allow the same email at two schools as separate accounts, and ask for the
school at sign-in.

- **Migration:** relax the unique email index to unique per school; login,
  password reset and invite acceptance all need a school. Breaks the
  "sign in with just your email" flow.
- **Privacy:** the most separate; the most confusing for parents, and two
  accounts with the same email invite mistakes in resets.

## Recommendation

**Option A**, done as its own project with its own security review,
because it's the only one that is simple for parents; **not before** the
pilot has run for a term. Until then, keep today's rule and tell the second
school to use a different email address for that parent (option C in
practice). Before building A, counsel should answer who controls the shared
login and what each school's notice must say [VERIFY].
