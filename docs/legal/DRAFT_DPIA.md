DRAFT — NOT LEGAL ADVICE — for review and adaptation by a qualified Kenyan data-protection advocate.

# Data protection impact assessment: a school using HouseMaster (draft)

*Filled in from the real system on 2026-09-28 (the code, its configuration
and docs/). The assessment belongs to the school as controller; HouseMaster
prepared this draft to help (DPA clause 6). The brief says a DPIA is
expected before high-risk processing, and a practitioner summary says it
must be submitted to the ODPC at least 60 days before the processing starts
[VERIFY: QUESTIONS_FOR_COUNSEL.md question 5]. The structure follows common
DPIA practice; check it against the ODPC's DPIA guidance note and template
[VERIFY], which could not be opened while this was written.*

## 1. The processing

**What:** a web application for a school's pupil records, grades,
attendance, report cards, parent-teacher messaging, announcements and
urgent alerts, used by the school's staff and by parents. Optional modules
(updated 2026-10-05): timetable, boarding (beds, roll calls, missing-boarder
records, leave, sick bay), support suggestions and plans, class positions,
and admissions with a public application form (PR #14, not yet merged).
Added by 2026-10-16: school fees and **M-Pesa collection** into each school's
own paybill or till; **pupils' own sign-in accounts**; homework, with pupils
handing work in; **behaviour records** and merits; parents' absence reports and
**absence alerts**; clubs and fixtures; the school calendar with private feed
links; and phone and browser notifications.

**Why (purposes):** to educate pupils and track their progress, report to
parents, communicate with families, keep pupils safe in emergencies, and
collect and account for school fees.

**Scale (typical pilot school):** a few hundred pupils, about as many
parent accounts, a few dozen staff. Many schools on one platform, each kept
separate.

**Why it may be high risk** [VERIFY the ODPC's criteria]: it concerns
**children**, who can now **sign in themselves**; it includes **health notes** and possibly other sensitive
data; it is **systematic** (every pupil, every day); it uses **new
technology** (an AI writing assistant); it includes **behaviour records** and
**families' finances** (fee balances and payments); and the data is **transferred
abroad** (US-based hosting).

## 2. Data flows

```
 Staff and parents (browsers, phones)
        │  HTTPS
        ▼
 Frontend (Vercel) ── pages only, no school records stored
        │  HTTPS API calls, with a sign-in token
        ▼
 Backend (Render) ── checks who you are and what you may see
        │  TLS
        ▼
 Database (Neon) ── every record
        │
        ├─ nightly: encrypted backup → GitHub Actions (90 days) [→ optional S3 copy]
        ├─ on request: minimised text → Google Gemini → draft back to the teacher
        ├─ invites, resets, notifications, urgent alerts → email provider → recipients
        ├─ notifications → the browser maker's push service (school name only) → devices
        ├─ M-Pesa: phone, amount, admission no. → Safaricom → result, code, payer name back
        │     (money goes to the school's own paybill; HouseMaster never holds it)
        └─ errors → Sentry (secrets in addresses removed first)
```

The data held is listed in the DPA, Annex A. Who each outside service is,
and what it receives: [SUBPROCESSORS.md](SUBPROCESSORS.md). What goes to
the AI: docs/AI_DATA_FLOW.md.

## 3. Necessity and proportionality

| Question | Answer from the system |
|---|---|
| Is each kind of data needed? | Core records (names, class, grades, attendance, reports) are the purpose. **Optional fields the school can leave empty:** health notes, photo, nationality, gender, parents' occupation and address. The school should decide which it really needs. |
| Is access limited? | Yes. Schools are fully separated; teachers see only their classes; parents only their own children and only finalised reports; admins can't read conversations they're not in. |
| Is the AI necessary and minimised? | It is optional (a teacher can write every comment). It receives no names or identifiers, a placeholder replaces the pupil's name, and a teacher always reviews the draft. |
| Are people told? | Parents and staff accept a privacy notice when they create an account; the school's notice (template provided) explains the processing. |
| Can people use their rights? | Admins can export a family's data and remove a pupil's personal data; parents can update their contact details and turn notification emails off. The export does not yet include boarding roll-call marks, the current house and bed, sign-up requests, invitations or activity-log entries [VERIFY whether it must]. |
| Is data kept only as long as needed? | A retention command anonymises former pupils after a period the school sets (off until set). Backups expire after 90 days. |
| Are transfers abroad justified? | [VERIFY: QUESTIONS_FOR_COUNSEL.md question 3.] |

## 4. Risks to children and families, and mitigations

Likelihood and severity: low / medium / high, **after** the mitigations in
place today.

| # | Risk | Mitigations in place | Likelihood | Severity | Residual |
|---|---|---|---|---|---|
| 1 | Another school, or a stranger, sees a child's records | Every query limited to the user's school, refusals indistinguishable from "not found", tested on every change; sign-in rate limits; sessions end on password change | Low | High | Low–medium |
| 2 | A parent sees another family's child or learns other parents' names | Parents see only linked children; direct messages can't mix families; parents can message only their children's teachers and admins | Low | High | Low (class discussions still show a class's parents to each other by design, question 8) |
| 3 | A parent is linked to a child who isn't theirs (wrong or fraudulent link) | Only admins link parents to children, by invitation or by approving a sign-up request with the admission number; every link and unlink is logged; the verification procedure (SCHOOL_guardian_verification_procedure.md) | Medium | High | Medium: depends on the school following the procedure |
| 4 | Health notes or other sensitive data disclosed | Visible to staff at the school only; parents see only their own child's; not sent to the AI; optional | Low | High | Low–medium |
| 5 | Data sent to the AI provider is kept or used for training | Minimised prompts (no names or identifiers); **paid no-training tier and DPA still to be put in place (H-8)** | Medium until H-8 | Medium | Low once H-8 is done |
| 6 | A stolen staff account is used to read or send data | Rate limits on sign-in; short sessions that end on password reset; admins can deactivate accounts; activity log; urgent alerts limited per school | Medium | High | Medium (no two-factor sign-in yet) |
| 7 | Data lost or corrupted | Nightly encrypted backups, each test restored; database point-in-time restore window (short on the free plan) | Medium until backups are switched on (H-1) | High | Low once H-1 is done |
| 8 | Emergency alert doesn't reach parents | Shown in the app and emailed; delivery and "seen" counts for the sender; a test alert for staff | Low | High | Low–medium (email depends on the provider; no SMS) |
| 9 | Personal data in error reports or logs | IP addresses and request bodies not sent to Sentry; reset links never logged; debug logging of IP addresses only when switched on | Medium | Low | Low |
| 10 | Transfers abroad without a lawful ground | [pending counsel, question 3] | — | Medium | Unknown until answered |
| 11 | Records kept longer than necessary | Retention command (off until the school sets a period); backups expire in 90 days | Medium | Medium | Low once a period is set |
| 12 | Public source code helps an attacker | Security relies on design and tests, not secrecy; secrets are never in the code | Low | Medium | Low (question 10) |
| 13 | A missing boarder is forgotten, or the record of it is lost | A boarder marked missing stays flagged until a person records how it was resolved (who, when); finished roll calls can only be corrected by an admin, with a reason, and the change is kept; a house with history can't be deleted (A-1 to A-3, PR #15) | Low | High | Low |
| 14 | Sick-bay and support records disclosed | Boarding staff see only their houses; support suggestions are never shared until a teacher confirms; parents see only their own child's confirmed concern; neither is sent to the AI; activity log entries hold IDs, not notes | Low | High | Low–medium |
| 15 | A pupil is wrongly labelled as needing support, or ranked on too little data | Suggestions need a minimum number of marks and attendance days, a person always confirms; a pupil with incomplete marks is shown as "not ranked" instead of being placed (C-1, D-1, PR #17) | Medium | Medium | Low |
| 16 | The public admissions form is abused: someone else's email, flooding, or finding out who applied | One confirmation email naming the school and nothing about the child; nothing reaches staff until confirmed; unconfirmed applications expire; per-address and per-email limits; the same answer whatever happened; duplicates merged (B-1 to B-3, PR #14) | Medium | Medium | Low |
| 17 | Admissions data kept for children who never join | Closed applications deleted after a school-set period (off by default); applications included in the family export and removal (B-4, PR #14); a recommendation to stop collecting health details before an offer (docs/DESIGN_health_notes_public_form.md) | Medium | Medium | Low–medium until the school sets a period |
| 18 | A fee payment is recorded twice, or a forged payment notice is credited, so a family's balance is wrong | M-Pesa notices are matched to a request the school made and checked against its own records; the same Safaricom code can't be credited twice from the same route; every payment, void and claim decision is logged | **Medium** (the readiness re-check found double-crediting under simultaneous clicks and when one payment is reported by two routes: PAY-001 to PAY-004, to fix before collecting money) | Medium | Medium until fixed |
| 19 | Someone takes over a school's M-Pesa connection, or redirects payments | Credentials encrypted and never shown again; callback addresses carry a long secret, now removed from error reports | **Medium** (only one person, the bursar, is needed to change the paybill, with no alert: PAY-006) | High | Medium until fixed |
| 20 | A behaviour record shared with parents names or describes another pupil | Staff choose what to share; staff-only notes are never shown; parents and the pupil see only that pupil's records | Medium | Medium | Medium: depends on staff not naming other pupils (school guidance) |
| 21 | A pupil's own account is misused (shared password, a sibling, a stranger) | Username, not email; a starting password the pupil must change; sign-in limits; the account sees only that pupil's record, never fees, other pupils or contact lists; the school can close it, and it closes when the pupil leaves | Low | Medium | Low |
| 22 | Absence reasons (often illness) or fee balances seen by the wrong person | Parents see only their own children; fees only for bursars and admins; absence reports removed with the pupil's personal data | Low | Medium | Low |
| 23 | A calendar feed link is forwarded and shows events to someone outside the school | The link holds a long secret; it shows only events the link's owner may see (staff-only events never reach parents); the owner can make a new link, which ends the old one | Medium | Low | Low |
| 24 | Notifications reveal something on a locked phone or to the browser maker | Notifications carry only the school's name and a short notice, never a child's name; they are encrypted for the device; each person turns them on for themselves | Low | Low | Low |
| 25 | A school's subscription lapses and staff and parents lose access to attendance, boarding and sick-bay records | Admins keep access to billing; the lock follows a grace period | **Medium** (today the lock covers everything: BILL-001 in the readiness re-check) | High | Medium until safeguarding features stay open |

## 5. Residual risk and actions

Actions that lower the residual risk, owner in brackets:

1. Put the paid no-training AI tier and Google's DPA in place (H-8, owner).
2. Switch on backups and run a restore drill (H-1, owner).
3. Decide which optional fields to use; leave health notes and photos
   empty unless needed (school).
4. Follow the guardian verification procedure (school).
5. Get counsel's answers on transfers, sensitive data, legal basis and
   retention, and set the retention period (owner, counsel, school).
6. Consider two-factor sign-in for admins (HouseMaster, future).
7. Decide whether the admissions form collects health or learning needs
   before an offer, and set the admissions retention period (school,
   counsel; docs/DESIGN_health_notes_public_form.md).
8. Close the gaps in the family export listed in section 3 (HouseMaster).
9. Fix the payment issues PAY-001 to PAY-006 before any school collects fees
   through HouseMaster (HouseMaster; risks 18 and 19).
10. Keep safeguarding features (attendance, boarding, sick bay, messaging)
    working when a school's subscription lapses (HouseMaster, BILL-001; risk 25).
11. Tell staff not to name other pupils in behaviour records shared with
    parents (school; risk 20).
12. Remove M-Pesa payer names and phone numbers when a pupil's personal data
    is removed, subject to counsel's answer on keeping financial records
    (HouseMaster, DP-002; question 19).

**Overall residual risk after actions 1–5:** [low / medium: for the
school's DPO and counsel to decide].

## 6. Consultation

- [Who at the school was consulted: head, DPO, a parent representative?]
- [Whether the ODPC needs to be consulted or the DPIA submitted, VERIFY.]

## 7. Sign-off

| Role | Name | Decision | Date | Signature |
|---|---|---|---|---|
| School head (controller) | | | | |
| School data protection officer | | | | |
| HouseMaster (processor) | | | | |
| Review due | | | [one year later, or on a significant change] | |
