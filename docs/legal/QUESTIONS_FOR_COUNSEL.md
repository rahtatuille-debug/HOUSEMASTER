DRAFT — NOT LEGAL ADVICE — for review and adaptation by a qualified Kenyan data-protection advocate.

# Questions for counsel

One list of everything the drafts could not settle. Each question says
what HouseMaster does today (from the code) and which draft depends on the
answer. See [README.md](README.md): the primary legal texts were not read
while these drafts were written, so the "working assumption" in each item
is only a starting point.

## 1. Registration scope

**Question:** must HouseMaster register with the Office of the Data
Protection Commissioner (ODPC), and in what capacity: processor,
controller, or both?

**Context:** the brief says registration has been mandatory since
14 July 2022 [VERIFY]; that a small-entity exemption (annual turnover under
KES 5 million and fewer than 10 employees) exists but does not apply to
processing for listed purposes that include operating an educational
institution [VERIFY]; and that the rules don't say whether a vendor serving
schools is caught by that listed purpose [VERIFY].

**Working assumption:** register as a processor, and also as a controller
for HouseMaster's own-purpose data (question 2).

**Affects:** ODPC_REGISTRATION_GUIDE.md, DRAFT_privacy_notice_housemaster.md.

## 2. Roles

**Question:** is the analysis in the drafts right? The school is the
controller of pupil, parent and staff data; HouseMaster is its processor,
and a controller in its own right for its own purposes: school admins'
account and contact details for running the service, billing, leads from
the website, product analytics and its own error telemetry (Sentry)
[VERIFY]. The brief notes that the role follows who decides the purposes
and means, not the contract's label [VERIFY].

**Specific points:**
- HouseMaster decides *how* report comments are drafted (Google Gemini, the
  prompt, the data minimisation in docs/AI_DATA_FLOW.md). Is that a "means"
  decision that could make it a joint controller for that feature?
- Error reports (Sentry) can contain fragments of school data. Is
  HouseMaster a controller for its own telemetry, and does the DPA need to
  allow it?

**Affects:** DRAFT_data_processing_agreement.md, both privacy notices, DRAFT_DPIA.md.

## 3. Cross-border transfer grounds, per sub-processor

**Question:** on which ground may each transfer in SUBPROCESSORS.md be made
(Neon and Render in the US, Vercel, Sentry, Google Gemini, the email
provider, GitHub Actions for backups, optional S3 storage)? The brief says
cloud hosting abroad is still a transfer and the Act allows transfers only
on a closed list of grounds [VERIFY]. What documents does each ground need
(the ODPC's cross-border guidance note, [VERIFY])?

**Also:** one practitioner summary claims a serving copy of personal data
must be kept on servers in Kenya. The drafts do not assert this. Is there
any such requirement for this kind of processing (for example for
"sensitive" data, or on public-interest grounds), and if so, which data?

**Affects:** SUBPROCESSORS.md, DRAFT_data_processing_agreement.md (Annex C), DRAFT_DPIA.md.

## 4. Sensitive-data status of parent-child links

**Question:** Kenya's definition of sensitive personal data is said to
include family details such as the names of a person's children and
parents [VERIFY]. HouseMaster stores, for every parent, which children they
are linked to, and the relationship (mother, father, guardian...). Does
that make the guardian-student link sensitive personal data? What extra
conditions follow?

**Also sensitive or special:** pupils' health notes (`medical_notes`),
gender, nationality and photos (see the DPIA's data inventory). Which of
these are sensitive under the Act [VERIFY], and should any be removed from
the product rather than protected?

**Affects:** DRAFT_DPIA.md, the school privacy notice template, SCHOOL_guardian_verification_procedure.md.

## 5. DPIA timing and submission

**Question:** is a DPIA required before a school starts using HouseMaster,
who carries it out (the school as controller, with HouseMaster's help?),
and must it be submitted to the ODPC? A practitioner summary says a DPIA
must be submitted at least 60 days before the processing starts [VERIFY].
If so, what does that mean for a pilot school already using the product?

**Affects:** DRAFT_DPIA.md.

## 6. Legal basis: consent or the school's function

**Question:** for pupils' records (grades, attendance, reports), what is
the school's lawful basis: consent from a parent, or the school's legal
obligations and functions (with consent only for extras)? The brief says
children's data needs parental or guardian consent and verification of the
guardian's authority [VERIFY]. HouseMaster today asks parents and staff to
accept the privacy notice when they create an account (`privacy_accepted_at`)
but does not collect consent for the school's core processing.

**Affects:** the school privacy notice template, SCHOOL_guardian_verification_procedure.md, DRAFT_DPIA.md.

## 7. Retention periods

**Question:** how long should each kind of record be kept after a pupil
leaves (grades, report cards, attendance, messages, the activity log,
backups)? Are there education-sector rules on keeping pupil records
[VERIFY]? HouseMaster has a retention command that anonymises pupils who
left more than N years ago, switched off until someone sets N
(`RETENTION_INACTIVE_STUDENT_YEARS`, docs/DESIGN_data_subject_tooling.md).

**Affects:** DRAFT_data_processing_agreement.md (Annex A), both notices, DRAFT_DPIA.md.

## 8. Messaging safeguards

**Questions:**
- Class discussions show a class's parents to each other by name. Is that
  covered by the school's privacy notice, or does it need each parent's
  consent (docs/SECURITY_NOTES.md, "Direct conversations don't mix
  families")?
- Staff can message parents and parents can message their children's
  teachers. Should schools be told to keep conversations about a child
  inside the platform, and who may read them (today: only the
  participants; admins cannot read conversations they are not in)?
- Should there be a safeguarding route by which the school's head can read
  a conversation, and how would that be disclosed?

**Affects:** the school privacy notice template, DRAFT_DPIA.md.

## 9. Entity structure

**Question:** who is "HouseMaster" in the contracts and the registration?
The drafts use "[HouseMaster legal entity]". A sole proprietor, a company
and a foreign entity may register and contract differently [VERIFY], and
the choice affects liability under the DPA.

**Affects:** every draft.

## 10. Public source code and due diligence

**Question:** the code of both repositories is public. Does publishing the
code of a system that processes children's data create any obligation or
risk (for example in a school's due diligence, or if a vulnerability is
found)? The owner is weighing making the repositories private
(HUMAN_ACTIONS.md, H-9).

**Affects:** DRAFT_DPIA.md (risks), the DPA's security annex.

## 11. AI processing

**Question:** report comments and announcement drafts are written by
Google Gemini from minimised data (no names, no identifiers,
docs/AI_DATA_FLOW.md), and a teacher always reviews them before anything
reaches a parent. Does the Act's rule on automated decision-making
[VERIFY] apply at all, given the human review? What must the notices say
about it? Is Google's standard data-processing addendum enough, on a paid
tier that doesn't use prompts for training?

**Affects:** both notices, SUBPROCESSORS.md, DRAFT_DPIA.md.

## 12. Breach notification between processor and controller

**Question:** the brief and a practitioner summary say a processor must
tell the controller "without delay" and, where practicable, within 48
hours, and a controller must tell the ODPC within 72 hours [VERIFY]. Which
wording and deadlines should the DPA use, and should HouseMaster commit to
a shorter time (the drafts say 24 hours)?

**Affects:** DRAFT_data_processing_agreement.md, DRAFT_breach_notification_templates.md, docs/RUNBOOK.md.

## 13. Fees and certificate validity

**Question:** what are the current registration fees for each tier, and
how long is a certificate valid? The brief says fees are tiered and the
certificate lasts two years [VERIFY current fees].

**Affects:** ODPC_REGISTRATION_GUIDE.md.

## 14. Parents with children at two schools

**Question:** if one parent login could see children at two schools
(GUARDIAN_MULTI_SCHOOL_DESIGN.md), who is the controller of that account's
data, and what must each school's notice say?

**Affects:** GUARDIAN_MULTI_SCHOOL_DESIGN.md.
