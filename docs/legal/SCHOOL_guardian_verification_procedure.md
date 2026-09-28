DRAFT — NOT LEGAL ADVICE — for review and adaptation by a qualified Kenyan data-protection advocate.

# Checking a parent or guardian before linking them to a child (school procedure, draft)

*Linking a parent to a child in HouseMaster lets that person see the child's
grades, attendance, finalised reports and school messages. A wrong link is
a data breach. The brief says processing children's data requires the
consent of a parent or guardian and verification of their authority
[VERIFY]; this is a practical procedure for that, for the school's
data protection officer to adopt or adapt.*

## Who may approve a link

Only a school **admin** can link a parent to a child in HouseMaster
(teachers can't). The school should name which admins do this, usually
the admissions officer or the head's office.

## What to check first

Check against the child's **admission records**, not against what the
person says:

1. **The person is named** in the admission file as a parent, guardian or
   person with parental responsibility, **or** they show a document that
   gives them that responsibility (for example a court order, a guardianship
   letter).
2. **Identity:** national ID or passport matches the name in the file (in
   person), or a call back to the phone number already in the admission
   file (at a distance).
3. **Contact details:** the email address they will sign in with is theirs
   (it receives the invitation link, which proves they control it).
4. **Restrictions:** check the file for any court order or safeguarding
   note restricting this person's access. **If there is one, don't link
   them**, and ask the head.

Record who checked, when and what was seen (not a copy of the ID) in the
school's own admissions records.

## How it maps to HouseMaster

There are two ways a link is made, and both need an admin's decision:

- **Invitation by the school:** Parents → Invite a parent. The admin enters
  the parent's name and email and **chooses the children**. The parent gets
  an email with a link and sets a password. Do the checks above **before**
  sending the invite.
- **Class sign-up link:** a parent fills in the class sign-up form with
  their name, email, phone, relationship and the child's **admission
  number**. That only creates a *request*: nothing is linked until an admin
  opens Parents → Sign-up requests and approves it. Do the checks above
  **before** approving; reject requests you can't verify.

HouseMaster records every link, unlink, approval and rejection in the
activity log (who did it and when).

## Correcting a wrong link

1. Parents → the parent → **Change children**, untick the wrong child and
   **Save children**. The link is removed at once and the activity log
   records "unlinked ...".
2. If the person should have no access at all: **Deactivate** the account.
   That ends all their sessions straight away.
3. Check the activity log for what they could have seen while wrongly
   linked, and treat it as a possible data breach (docs/RUNBOOK.md and
   DRAFT_breach_notification_templates.md).

## When a child leaves or circumstances change

- When a child leaves, **Deactivate** them (Students, or their profile).
  Their parents **still see** the child's records (for example old report
  cards) until the link is removed: if the school doesn't want that, also
  untick the child under Parents → **Change children**. Decide the school's
  policy on this with counsel (retention, QUESTIONS_FOR_COUNSEL.md
  question 7).
- When a court order or a family change affects access, update the links
  the same day.
