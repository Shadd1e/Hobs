# Staff permission system

## Roles (low to high, each inherits everything below it)
- **receptionist** — WhatsApp only. Can book/check-in/check-out rooms
  (after a confirm-once round trip). Cannot cancel a paid/checked-in
  booking. Cannot edit prices. No dashboard access.
- **manager** — everything receptionist can, plus: edit room prices,
  cancel paid bookings, full admin drill-down on the dashboard, gets
  WhatsApp alerts on high-impact actions, can review/revert flagged
  actions (WhatsApp `undo <code>` or dashboard button).
- **top_manager** — everything manager can, plus: assign staff roles from
  the dashboard. This is the ONLY thing top_manager can do that manager
  can't, and it is deliberately impossible to do via WhatsApp — see below.

Legacy values `front_desk` (= receptionist) and `admin` (= top_manager)
are still accepted for any rows seeded before this system existed.

## Why permission changes are dashboard + email-code only
WhatsApp identity is just a phone number. A lost phone, a SIM swap, or a
staff member who left without being deactivated all mean "control of that
WhatsApp number" is not a strong enough guarantee to grant someone
elevated access. So role changes:
1. Can only be initiated from the dashboard by a `top_manager`.
2. Require a 6-digit code emailed to *that same top_manager's* registered
   email (never the target staff member's).
3. Expire after 10 minutes, single confirm attempt window of 5 tries.
There is no code path anywhere that lets a WhatsApp message change anyone's role.

## High-impact actions
Currently: cancelling a PAID or CHECKED_IN booking. These execute
immediately (front desk isn't blocked from working) but are logged with
`is_high_impact=True`, which triggers:
- A WhatsApp alert to every manager+ at that hotel with a revert code
- A 15-minute revert window (shown as a countdown to the manager)
- Inclusion in the weekly digest regardless of whether it was reviewed

## Audit trail
`StaffActionLog` is append-only. A revert never edits or deletes the
original row — it writes a NEW row (`action="revert"`) and links back via
`reverted_by_log_id`. This is deliberate: if a hotel owner ever needs to
prove what happened (staff dispute, insurance claim, audit), the log has
to hold up as a genuine record.

**Separation of duties**: whoever performed a flagged action can never be
the one to review/revert it — enforced in `StaffAuditService._do_revert`,
not just a UI convention.

## What's NOT built yet
- Self-service password reset for staff dashboard logins
- Invite-by-email onboarding flow for new staff (a top_manager currently
  sets `password_hash` directly)
- Trust/reliability score per staff member (proposed, not built)
- Voice note transcription for WhatsApp updates (proposed, not built)
