# Design note: notifications beyond email

Status: note only (G). Nothing here is built. No prices are quoted: get current pricing from each provider before
choosing ([VERIFY]); none was checked for this note.

## Today

- **Email only.** All parent and staff notifications are email, sent through SMTP after the database transaction
  commits (`guardians/notifications.py`, `communications/alerts.py`). Production still needs an email provider
  (`docs/HUMAN_ACTIONS.md`).
- **Urgent alerts** also show in the app, with "seen" counts. There is no SMS, WhatsApp or push.
- **Parents' preferences.** Parents record a preferred contact (call, SMS, WhatsApp, email) on their profile. It is
  shown to staff and not used for sending.
- **Opt-out.** Parents can turn notification emails off; urgent alerts ignore that switch.

## What families need

In Kenya and similar markets many parents read SMS or WhatsApp sooner than email. A missing-boarder alert, a
sick-bay visit or an urgent closure should reach them in minutes.

## Options

| | Channel | For | Against |
|---|---|---|---|
| A. SMS gateway | A Kenyan aggregator (e.g. Africa's Talking) or an international one; a sender ID registered for the school or for HouseMaster | Reaches every phone; good for urgent alerts | Per-message cost; sender ID registration takes time; the content must stay short and contain no sensitive detail |
| B. WhatsApp Business Platform | Template messages through Meta or a provider | Widely used; rich messages | Templates need approval; per-conversation pricing; another sub-processor transferring data abroad |
| C. Web push | The installable app (service worker) with VAPID keys | No per-message cost; no new sub-processor | Only works where the app is installed and allowed; unreliable on some phones |
| D. Email only, better | Digest and "seen" tracking | No new cost | Doesn't solve reach |

## Recommendation

- **C for everyday notices** (free, no new processor).
- **A for urgent alerts only**, opt-in per school, with a small per-school monthly cap so cost can't run away.
- **One message layer:** route every notification through a single function choosing channels by kind (urgent vs
  routine) and the parent's preference. Log only the kind, the channel and the delivery status, never the text.
- **Before building A or B**, the owner chooses a provider and sender name, and adds it to SUBPROCESSORS.md and the
  DPA annex. Counsel confirms transfer grounds (QUESTIONS_FOR_COUNSEL.md, question 3).
