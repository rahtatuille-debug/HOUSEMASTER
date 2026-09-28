# Communications: what exists (B-9 inventory)

Written before any B-9 code was changed, from the code on
`claude/followup-2-lists-and-timezone`. The last section lists what B-9
then added.

## (a) A teacher messaging all parents of one class in one action

**Status: exists.** Missing when inventoried: a rate limit.

| Aspect | What the code does | Where |
|---|---|---|
| Endpoint | `POST /api/conversations/class/` with `school_class`, `kind` and `body` | `messaging/views.py`, `ConversationViewSet.class_message` |
| Two kinds | `class_notice`: one-way; parents can read but not reply, and don't see who else received it. `class_group`: a discussion; everyone can post and sees the other members | `messaging/models.py` (`Conversation.Kind`), `messaging/classes.py` (`can_post`), `messaging/serializers.py` (`get_participants` hides recipients of a notice from parents) |
| Who may send | Staff only. Teachers only to classes they are assigned to (`TeachingAssignment`); admins to any class at their school. Parents get 403 | `class_message` |
| Audience | Worked out on the server from the class: active parents with an active child in the class (`class_parent_users`). The client sends only a class ID, which must belong to the sender's school ("Class not found." otherwise) | `messaging/classes.py` |
| Membership over time | Parents who join the class are added on the next message; parents who leave lose access at once (list filter), and are removed on the next message | `sync_class_participants`, `ConversationViewSet.get_queryset` |
| Delivery | In-app only: one participant row per parent, shown in their Messages inbox with an unread count. No email | `start_class_conversation` |
| Failures | Nothing to fail per recipient in-app. A class with no parent accounts is refused (400) | `class_message` |
| Audit trail | `class_message.created` in the activity log, with the number of parents | `class_message` |
| Rate limit | **None** | |
| Other families | A notice never shows parents to each other. A discussion does, by design (docs/SECURITY_NOTES.md, B-5; question for counsel) | |
| Frontend | Messages → "Message a class": notice or discussion; "parents can't reply" shown on notices | `src/panels/Messages.jsx` |
| Tests | `messaging/tests.py` `ClassMessageTests`: reaches every parent of the class only; teachers limited to their classes; parents refused; joiners and leavers; empty class refused; another school's class refused | |

## (b) Emergency (urgent) alerts

**Status: partial.** Missing when inventoried: email on every alert, a
per-school rate limit, and a staff-only test alert.

| Aspect | What the code does | Where |
|---|---|---|
| Endpoint | `POST /api/alerts/` (`title`, `body`, `audience`, `year_group` / `school_class`, `send_email`); `GET /api/alerts/active/`; `POST /api/alerts/{id}/acknowledge/`; `GET /api/alerts/{id}/recipients/`; `POST /api/alerts/{id}/end/` | `communications/views.py`, `UrgentAlertViewSet` |
| Who may send | Admins: any audience (everyone, all staff, all parents, a year group's parents, a class's parents). Teachers: only the parents of a class they teach. Parents: never | `perform_create` |
| Audience | Worked out on the server when the alert is sent, and frozen as one `AlertRecipient` row per person: active staff and/or active parents at the school, parents matched through their active children's class or year group; the sender is left out. Nobody with an account → 400 | `communications/alerts.py` |
| What people see | A red "Urgent" banner at the top of every page until they tap "I've seen this"; admins' home page lists active alerts with "seen by N of M" | frontend `src/App.jsx` (`urgent-banner`), `src/panels/Home.jsx`, `src/panels/Alerts.jsx` |
| Who sees which alert | Recipients only (plus the sender and the school's admins), and only at their own school | `get_queryset`, `active` |
| Confirmation | The frontend asks "Send this urgent alert to … now?" before sending, and again before ending one | `src/panels/Alerts.jsx` |
| Channels | In-app always. Email **only if the sender ticks "also email"**, sent one by one inside the request | `perform_create`, `email_alert` |
| Delivery counts | `recipient_count`, `acknowledged_count`, and after email `emailed_count` / `email_failed_count`; the recipients list shows who has and hasn't seen it | serializer, `recipients` |
| Failures | One failed email doesn't stop the others or the in-app alert (tested) | `email_alert` |
| Quiet hours or digests | None exist anywhere in the product. Parents can turn off *notification* emails (announcements, reports); alert email doesn't look at that setting | `guardians/models.py` (`email_notifications`), `guardians/notifications.py` |
| Audit trail | `alert.sent` (audience, count, emailed), `alert.acknowledged` per person, `alert.ended` | activity log |
| Rate limit | **None**: an admin account could send any number of alerts to every parent | |
| Test alert | **None** | |
| Tests | `communications/tests.py`: everyone at own school only; teachers limited to own class parents; parents refused; ending removes the banner; people only see alerts sent to them; other school can't see them; no recipients refused; class alert emails only that class; email failure still sends the alert | |

## What B-9 added

- **Class messages:** a per-sender rate limit (`CLASS_MESSAGE_RATE`, default
  30 an hour), with the same friendly "please wait" answer as other limits.
  Email for class messages was **not** added: messages are an in-app inbox
  today, and emailing parents about every class notice is a product
  decision (with the parents' opt-out to respect), not a gap in safety.
- **Urgent alerts:**
  - Every alert is emailed as well as shown in the app (the `send_email`
    field is still accepted but no longer needed). Email goes out in the
    background after the alert is saved, so a whole-school alert can't time
    out the request; the counts are filled in when sending finishes.
    A parent's "no notification emails" choice doesn't apply to urgent
    alerts, and there are no quiet hours or digests that could hold one
    back (tests pin this down).
  - A per-school limit: `ALERT_SCHOOL_RATE` (default 10 a day) for real
    alerts, so a stolen admin login can't flood every parent, and a separate
    `ALERT_TEST_SCHOOL_RATE` (default 5 a day) for test alerts, so testing
    never uses up the budget for a real emergency.
  - **Test alerts:** `POST /api/alerts/` with `"is_test": true` (admins only)
    goes to all staff and nobody else, whatever audience is given, is
    marked "TEST" in the banner and email subject, and exercises both
    channels.
- Frontend (its own commit on `claude/followup-2-lists-and-timezone` in the
  frontend repository, the branch plan having no communications branch
  there): the "also email" box is gone (email is always sent), a "Send a
  test alert to staff" button, a "TEST" badge, and a friendly message when
  a limit is reached. That frontend still sends `send_email: true` and, for
  a test, `audience: "all_staff"`, so against a backend without B-9 it
  still emails, and a test can only ever reach staff (as an ordinary alert
  titled "Test alert").
