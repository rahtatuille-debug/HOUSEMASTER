# Design note: who may authorise a boarder's leave, and who may collect them

Status: note only (G). Nothing here is built. School-policy decisions are marked [VERIFY] (`docs/HUMAN_ACTIONS.md`).

## Today (boarding/views.py, LeaveViewSet)

- **Who requests.** A parent linked to the child requests leave in the app. Staff can also give leave directly, and it
  is approved straight away.
- **Who decides.** Any member of the house's boarding staff, or any admin, can approve, decline, sign out, sign in
  or cancel. No rule says which kinds of leave need a more senior person.
- **Who collects.** `collected_by` is free text typed by the parent or staff. Nothing checks it against a list of
  people the family has authorised, and nothing is recorded at the gate beyond who signed the boarder out.
- **Notification.** The parents are emailed when leave is approved or declined. The other parent is emailed too only
  if they are linked to the child and have notification emails on.

## Risks

1. A child released to someone the family didn't authorise (the main safeguarding risk). The name is free text, and
   the gate can't check it.
2. One parent requesting leave that the other parent, or a court order, doesn't allow. The school knows about orders;
   the app doesn't. [VERIFY with schools how this is handled on paper today]
3. Long or unusual leave (e.g. a week's exeat abroad) approved by one junior staff member.

## Options

| | What | For | Against |
|---|---|---|---|
| A. Authorised collectors | Per student: `AuthorisedCollector(name, relationship, phone, id document last 4, photo optional, added by, approved by admin)`; leave picks a collector from the list; the gate sees the name and photo when signing out | Closes risk 1; mirrors paper "pick-up lists" | Data about non-users (consent, retention); the admin keeps the list current |
| B. Approval levels | Settings per leave kind: who may approve (house staff / deputy / head), and a maximum length for house staff | Closes risk 3 | Needs roles beyond teacher/admin |
| C. Restrictions | A staff-only flag on the student: "leave only with admin approval", with an optional note visible to boarding staff | Small; covers risk 2 without modelling court orders | Relies on staff setting it |
| D. Both parents notified | Email every linked parent on any approval | Tiny change | Still after the fact |

## Recommendation

C and D first (small, high value), then A. B only if a school asks for it.

- **A's data** needs its own lawful basis and retention. Add it to the DPA annex and the school notice when built.
- **[VERIFY with pilot schools]** their pick-up policy, and whether a photo is acceptable.
