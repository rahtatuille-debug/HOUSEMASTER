# What leaves HouseMaster when the AI is used

HouseMaster uses one AI provider, **Google Gemini** (the `google-genai`
SDK), for two features. Every call goes through `reporting/ai.py`. Nothing
else in the app talks to an AI service.

The contract side (a paid Gemini tier whose terms rule out training on
prompts, and a data-processing agreement) is a human task, H-8 in
[HUMAN_ACTIONS.md](HUMAN_ACTIONS.md). Until it is done, treat anything sent
as potentially retained by the provider.

## 1. Report comments (`reporting/services.py`)

Triggered by a teacher or admin pressing "Generate" for one student and
term, or generating a whole class one student at a time.

| Sent to Gemini | Why |
|---|---|
| The placeholder `[STUDENT]` instead of the name | The model needs something to call the student |
| Term name (e.g. "Term 1") | So the comment refers to the right period |
| Each grade: subject name, score, maximum, percentage and level (e.g. "Mathematics: 81.00/100.00 (81%, EE)") | The substance of the comment |
| Attendance counts for the term (present, absent, late, excused) | The substance of the comment |
| The school's education system, its words for year group, class, subject and term, and British or American spelling | So the wording matches the school |
| The school's chosen tone (formal, warm or concise) | Style |

**Never sent:** first name, last name, admission number (`external_id`),
date of birth, gender, nationality, house, class name, medical notes,
attendance notes, photo, anything about parents, the school's name.

When the text comes back, `[STUDENT]` (in any case or spacing, or a bare
upper-case `STUDENT`) is replaced **on our server** by the student's first
name. The prompt tells the model not to guess a name or a gender. The result
is always a draft that a teacher reviews before it goes anywhere.

## 2. Announcement drafts (`communications/services.py`)

Triggered by a staff member typing a short brief and pressing "Write it for
me". The brief is free text, so it may contain names.

| Sent to Gemini | Why |
|---|---|
| The brief, with the full names of the school's pupils and parents replaced by `[PERSON 1]`, `[PERSON 2]`…, and email addresses by `[EMAIL 1]`… | The content of the announcement |
| The audience (e.g. "All parents") and, if chosen, the year group or class name | So the draft addresses the right people |
| The school's tone, words and spelling (as above) | Style |

**Never sent:** the school's name. The placeholders are swapped back on our
server when the draft returns.

**Residual risk:** a first name on its own ("Amina did well"), a nickname or
a misspelled name is not recognised and would be sent as typed. Staff should
be told not to put pupils' details in the brief. The generated text is never
published automatically.

## Limits and failure behaviour

- Each call has a 20-second HTTP timeout (`GEMINI_TIMEOUT_SECONDS`) and a
  hard deadline 5 seconds after that.
- Provider or network failures return 503 "The writing assistant is busy,
  please try again in a minute." Nothing is saved.
- Per-user limits: 30 report generations per hour, 5 whole-class runs per
  hour and 30 announcement drafts per hour (env-overridable, see
  [ENVIRONMENT.md](ENVIRONMENT.md)).
- The model is `GEMINI_MODEL` (default `gemini-3.5-flash-lite`).
