# Design note: health information on the public application form

Status: proposal (B-4). No code changes here. A school-policy and legal decision is needed: see [VERIFY] markers.

## Where things are today

- The public form (`/apply/<link>`) has one free-text field: "Health or learning needs the school should know about". It is stored in `Application.medical_notes`.
- Anyone with the link can send the form. Since B-1, nothing reaches staff until the family confirms their email, and an unconfirmed application is deleted when its link expires.
- **Who sees it.** Admins can read the application, including this field. It is copied into the student's health notes on enrolment.
- **Export and removal.** Since B-4 it is in the family data export and removed by the remove-personal-data tool.
- **Retention.** Closed applications can be purged after a school-set retention period, which is off by default.
- **Logging.** Activity log entries never contain it.
- Health information is special-category / sensitive personal data under the Kenya Data Protection Act 2019 (s. 2 and Part IV), UK GDPR (Art. 9) and similar laws. [VERIFY: which laws apply per school country.]

**Risks:**
- Families type detailed diagnoses into free text before any relationship with the school exists.
- Most of what they type is never needed if no place is offered.
- Admins who are not the school nurse or SENCo can read it.

## Options

| | What it means | For | Against |
|---|---|---|---|
| A. Keep as is | Free text on the form, copied to the student on enrolment | No change; families can raise anything early | Collects sensitive data from everyone, mostly unneeded; widest access |
| B. Yes/no question only | "Does your child have health or learning needs we should discuss? (yes/no)". Details are collected after an offer, through the parent account | Data minimisation; the school still knows to ask; details go only to students who join | One more step for families with real needs; schools lose early detail for planning (e.g. SEN provision before an offer) |
| C. Keep free text, restrict it | As A, but hidden from the pipeline list. Shown only to admins who open the application, and deleted from declined/withdrawn applications after a short fixed period (e.g. 30 days) even if retention is off | Keeps early information; narrows exposure | Still collects from everyone; needs a "health access" permission that doesn't exist yet |
| D. Remove the field | Ask nothing; collect after enrolment | Least data | Schools must ask separately; families with needs may feel unheard |

## Recommendation

**Option B.**

- Replace the free-text field with a yes/no question.
- Collect the details only once a place is offered, through the parent account. That account already supports health-notes suggestions that the school approves.
- This is the data-minimisation choice: the school learns that a conversation is needed without holding diagnoses for children who never join.
- It needs no new permission model, and it reuses an existing flow.

**Migration path, if chosen:**
- Keep the column for existing rows.
- Stop showing the field on the form; add the yes/no question as a new boolean.
- Leave existing text visible to admins until the school's retention rule or the purge removes it.
- The enrolment copy keeps working for old applications.

**Decisions for the school owner** (see `docs/HUMAN_ACTIONS.md`):
- [VERIFY] Whether the school's lawful basis and privacy notice cover collecting health data at application stage. The form's privacy notice today is the general parent notice; it does not mention application-stage health data specifically.
- [VERIFY] Whether any school needs SEN information before an offer (e.g. to decide whether it can meet a need). If so, Option C is the fallback for that school.
