DRAFT — NOT LEGAL ADVICE — for review and adaptation by a qualified Kenyan data-protection advocate.

# Data processing agreement

**Between** [School legal name], of [address] ("the School", the data
controller)
**and** [HouseMaster legal entity], of [address] ("HouseMaster", the data
processor).

**Status:** a draft for counsel. The clauses follow the contents the brief
says the ODPC expects in a controller-processor contract: subject matter,
data types, nature and duration, instructions-only processing, security,
staff confidentiality, help with data-subject rights, sub-processors and
flow-down, breach notification, deletion or return at the end, audit and
inspection, and liability [VERIFY against the Data Protection (General)
Regulations, 2021 and ODPC guidance]. See [README.md](README.md) on what
was not checked, and [QUESTIONS_FOR_COUNSEL.md](QUESTIONS_FOR_COUNSEL.md).

---

## 1. What this agreement covers

1.1 The School uses HouseMaster, a web application for student records,
grades, attendance, report cards, messaging between school and parents,
announcements and urgent alerts. HouseMaster processes personal data on the
School's behalf to provide it. Annex A describes the processing.

1.2 The School is the controller of that data and decides why it is
processed. HouseMaster processes it only to provide the service to the
School. [VERIFY: the role analysis, QUESTIONS_FOR_COUNSEL.md question 2.]

1.3 HouseMaster is a controller, not a processor, for the limited data it
uses for its own purposes: the account details of the School's
administrators for running and billing the service, its own error
telemetry and security logs, and enquiries sent to it. That processing is
covered by HouseMaster's own privacy notice, not this agreement. [VERIFY:
QUESTIONS_FOR_COUNSEL.md question 2.]

## 2. Instructions

2.1 HouseMaster processes the School's personal data only on the School's
documented instructions. This agreement, and the School's use of the
application's features and settings, are those instructions.

2.2 HouseMaster will not use the School's personal data for any other
purpose, including: training or improving machine-learning models,
benchmarking across schools, marketing, or selling or sharing it with
anyone. (Using pupil data for such purposes would make HouseMaster a
controller for them [VERIFY].)

2.3 If HouseMaster thinks an instruction breaks the law, it will tell the
School straight away and may suspend that processing until the School
confirms or changes it.

2.4 If a law requires HouseMaster to process the data other than on the
School's instructions, HouseMaster will tell the School first, unless the
law forbids that.

## 3. Confidentiality

3.1 Everyone at HouseMaster who can access the School's personal data is
bound by a written duty of confidentiality, and has access only as far as
their work needs it.

## 4. Security

4.1 HouseMaster keeps the technical and organisational measures in Annex B
in place, and will not reduce the protection they give without telling the
School first.

4.2 HouseMaster will review the measures at least once a year and after any
significant incident.

## 5. Helping the School with people's rights

5.1 Where a pupil, parent or member of staff asks the School to see,
correct, delete or move their data, or objects to its use, HouseMaster will
help the School respond within the time the law allows. The application
lets the School's administrators export, for a pupil and their parents,
the pupil's record, parents' details, grades, attendance, report cards, subject comments, the parents' messages and conversations about the pupil, support concerns, and boarding leave and sick-bay visits (as a spreadsheet or JSON). It does **not** yet include boarding roll-call marks or the current house and bed, parent sign-up requests and invitations, or activity-log entries naming the pupil; admissions applications are added by the admissions change (PR #14, B-4). [VERIFY: whether these must be included for a complete access request; see FIX_REPORT.md, additional observations.] They can also correct records and remove a pupil's personal data
(docs/DESIGN_data_subject_tooling.md).

5.2 If a request comes to HouseMaster directly, HouseMaster will pass it to
the School without answering it itself.

## 6. Helping the School meet its other duties

6.1 HouseMaster will give the School the information it reasonably needs
for a data protection impact assessment (a draft is in DRAFT_DPIA.md), for
consulting the ODPC, and for keeping its records of processing.

## 7. Sub-processors

7.1 The School authorises the sub-processors in Annex C.

7.2 HouseMaster will tell the School at least [30] days before adding or
replacing a sub-processor. The School may object on reasonable data
protection grounds; if the parties can't resolve the objection, the School
may end this agreement and the service without penalty.

7.3 HouseMaster will bind each sub-processor, in writing, to data
protection obligations at least as protective as this agreement, and
remains responsible to the School for them.

7.4 Transfers outside Kenya happen only on a ground the law allows
[VERIFY: grounds and paperwork, QUESTIONS_FOR_COUNSEL.md question 3].

## 8. Personal data breaches

8.1 HouseMaster will tell the School without undue delay, and in any case
within **24 hours** of becoming aware of a personal data breach affecting
the School's data. (The brief says the law requires a processor to tell the
controller without delay, and where practicable within 48 hours [VERIFY];
24 hours is a proposed stricter commitment for counsel to confirm.)

8.2 The notice will give what HouseMaster knows at the time, using the
template in DRAFT_breach_notification_templates.md, and HouseMaster will
send more as it learns it. It will not notify the ODPC, parents or anyone
else about the School's data itself unless the School asks it to or the
law requires it.

8.3 HouseMaster will take reasonable steps to contain the breach and
reduce its effects, and keep a record of it.

## 9. When the agreement ends

9.1 When the service ends, HouseMaster will, as the School chooses, give
the School an export of its data in a common format and then delete it, or
simply delete it, within [30] days, unless the law requires it to keep
some.

9.2 Encrypted backups containing the School's data expire on their own
within 90 days (docs/BACKUPS.md) and are not restored except to recover
from an incident.

9.3 HouseMaster will confirm the deletion in writing.

## 10. Audits and inspection

10.1 HouseMaster will give the School the information needed to show it
meets this agreement, and allow audits by the School or an auditor it
appoints, on reasonable notice, at most once a year unless a breach or the
ODPC requires otherwise. The ODPC may inspect as the law allows [VERIFY].

## 11. Liability

11.1 [For counsel: liability for breaches of this agreement and of the Act,
any cap, and indemnities. Note the question of which entity signs,
QUESTIONS_FOR_COUNSEL.md question 9.]

## 12. Term, law and precedence

12.1 This agreement lasts as long as HouseMaster processes the School's
personal data. It is governed by the laws of Kenya. If it conflicts with
any other agreement between the parties about personal data, this
agreement wins.

Signed for the School: ____________________ Name, role, date
Signed for HouseMaster: __________________ Name, role, date

---

## Annex A: The processing

**Subject matter:** providing HouseMaster to the School.

**Duration:** for as long as the School uses the service, then until
deletion under clause 9.

**Nature and purposes:** storing and displaying school records; recording
grades and attendance; drafting, reviewing and releasing report cards
(including AI-drafted comments that a teacher always reviews first);
messages between staff and parents; announcements and urgent alerts
(in-app and by email); invitations and sign-in; data-subject exports and
removal; backups; security logging. Where the School turns them on or uses
them: the timetable; boarding (houses and beds, roll calls, missing-boarder
records, leave and the sick bay); suggestions of pupils who may need support
and the support plans staff confirm; class and year-group positions; and
admissions (a public application form and the pipeline to enrolment, added by
PR #14).

**People the data is about:** pupils (including former pupils), their
parents and guardians, the School's staff, and people invited to the
School's account.

**Categories of personal data**, from the application's data model:

| About | Data |
|---|---|
| Pupils | first and last name; admission number; class, year group, house and curriculum pathway; enrolment, leaving and graduation dates; active or not; gender; date of birth; nationality; mode of learning; health notes; photo |
| Pupils' school records | grades (by subject, term and assessment type); per-subject comments, effort and targets; subject choices and levels; attendance (date, present/absent/late/excused, notes); report cards (progress summary, teacher's comment, head's comment, competency ratings, status, who submitted and finalised them and when) |
| Parents and guardians | name; email address; phone numbers; relationship to the child; postal address; occupation; preferred contact method; which children they are linked to; whether they want notification emails; when they accepted the privacy notice; an admin's note about them; sign-up requests (name, email, phone, relationship, the admission number they gave) |
| Staff | name; email address; role (teacher or admin); classes and subjects they teach; when they accepted the privacy notice |
| Communications | messages and conversations (who, when, content, read status); announcements; urgent alerts and who has seen them |
| Accounts and security | login email; password (stored only as a salted hash); password-reset and invitation records; a session version number used to sign people out |
| Audit trail | the activity log: who did what, when, with a short description (names of the people involved) |
| Timetable | lessons (class, subject, teacher, room, day and period); mostly about staff and classes rather than individual pupils |
| Boarding (if the School turns it on) | boarding house, dormitory and bed; roll-call marks (present, missing, on leave, in the sick bay) with notes; records of a boarder marked missing and how it was resolved (who, when, a note); corrections to finished roll calls (who, when, reason); leave requests (dates, reason, who collects the child, decision and notes); sick-bay visits (complaint, treatment, outcome, times) |
| Support | suggestions that a pupil may need support (computed from marks and attendance, never shared until a person confirms), confirmed concerns (reasons, teacher's note, support plan, review date, who and when), and the pupil's average and attendance when a suggestion was dismissed |
| Positions | class and year-group positions and "most improved", computed on demand from grades (not stored), shown to staff and on 8-4-4 report cards |
| Admissions (PR #14) | applicant's name, date of birth, gender, nationality, current school, day or boarding, health or learning needs, notes from the family; the parent's name, email, phone and relationship; whether the email was confirmed; staff notes, interview date, decision and decision note; the admission number given on enrolment |

**Data that may be sensitive personal data** [VERIFY which, under the
Act's definition: QUESTIONS_FOR_COUNSEL.md question 4]: pupils' health
notes, gender, nationality and photos, and possibly the parent-child links
themselves; **sick-bay visits** (complaints and treatment); **support
concerns and plans**, which can reveal special educational needs; records of
a boarder going missing; and the **health or learning needs** a family types
into the admissions form (docs/DESIGN_health_notes_public_form.md). The
School decides whether to record health notes and photos at all, and whether
to turn boarding and admissions on.

**Retention:** as the School sets it. Former pupils can be anonymised
automatically after a period the School chooses (off until set;
QUESTIONS_FOR_COUNSEL.md question 7).

## Annex B: Technical and organisational measures

These are the controls actually in the code as of the follow-up release.
References are to the repository.

**Keeping schools apart**
- Every record belongs to one school. Every list and lookup is limited to
  the requester's school; another school's record answers exactly like one
  that doesn't exist (accounts/mixins.py, accounts/test_isolation.py).
- Teachers see only the classes they teach; parents see only their own
  linked children.

**Accounts and sessions**
- Passwords at least 10 characters, stored as salted hashes (Django's
  password hashing).
- Short-lived sign-in tokens (60 minutes) with refresh tokens that rotate
  on every use and are retired on sign-out; changing or resetting a
  password, or deactivating an account, ends every session at once.
- Limits on failed sign-ins, password-reset requests, invitation and
  sign-up attempts, per address and per account (accounts/throttles.py).
- The Django administration site is at a secret address and its failed
  sign-ins are limited.

**Messaging and alerts**
- Parents can message only their own children's teachers and the admins;
  a direct conversation never mixes unrelated families; refusals don't
  reveal who exists (messaging/contacts.py).
- Urgent alerts are limited per school; test alerts go to staff only.

**Data minimisation in AI features**
- Report comments are drafted from marks and attendance with a placeholder
  instead of the pupil's name; announcement briefs have known names and
  email addresses masked. A teacher reviews every draft before anything
  reaches a parent. Details: docs/AI_DATA_FLOW.md.

**Encryption and transport**
- All traffic is HTTPS, with HSTS. The database connection string used in
  production requires TLS (`sslmode=require`, docs/ENVIRONMENT.md).
- Nightly backups are encrypted (AES-256, with GPG) with a passphrase kept
  outside GitHub, taken by a read-only database account, and each is test
  restored (docs/BACKUPS.md).

**Web security**
- Security headers and a Content-Security-Policy on the web pages; no
  third-party scripts or fonts; a strict CORS list.
- The application refuses to start in production with a missing or unsafe
  setting (docs/ENVIRONMENT.md).

**Accountability**
- An activity log of changes and sensitive actions (who, what, when),
  visible to the School's admins.
- Teachers' changes to school structure and pupil deletions need an
  admin's approval.
- Data-subject tools: an export per family (contents and current gaps in
  clause 5.1), removal of a pupil's personal data, and retention commands
  (former pupils; closed admissions applications once PR #14 is merged).
- Automated tests of all of the above run on every change, and changes
  reach production only through reviewed pull requests with passing tests
  (once branch protection is on, HUMAN_ACTIONS.md, H-7).

**People and process**
- An incident runbook (docs/RUNBOOK.md) and breach templates
  (DRAFT_breach_notification_templates.md).
- [For the owner: who at HouseMaster has production access, how access is
  granted and removed, and staff confidentiality undertakings.]

## Annex C: Sub-processors

As listed in [SUBPROCESSORS.md](SUBPROCESSORS.md) on the date of signing.
