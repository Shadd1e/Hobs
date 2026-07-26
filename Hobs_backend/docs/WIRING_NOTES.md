# Wiring notes — read before touching payments

## Payment provider: Flutterwave, not Paystack

Despite variable/file names saying "paystack" in places, this deployment
uses **Flutterwave** as the actual payment processor.

### The naming mismatch (confirmed by reading the inherited code directly)
It runs the OPPOSITE direction from what was first assumed:
- `app/models/flutterwave_subaccount.py` (table `flutterwave_subaccounts`) —
  despite the accurate-sounding name, ShoprHQ's `PaystackSubaccountService`
  actually calls the REAL Paystack API (`api.paystack.co/subaccount`) and
  writes the result into this table. The table name is a historical leftover
  (ShoprHQ probably started on Flutterwave, switched to Paystack, never
  renamed the table). So in the ShoprHQ codebase, `FlutterwaveSubaccount`
  rows are actually Paystack subaccounts.
- For HoBS: the `FlutterwaveSubaccount` model's *shape* (account_bank,
  account_number, business_name, split_value, split_type, subaccount_id) is
  exactly what a real Flutterwave subaccount needs, so we reuse the MODEL
  as-is. What we do NOT reuse is `PaystackSubaccountService` — that class
  calls Paystack's real endpoints. Instead, `FlutterwaveSubaccountService`
  (new) calls Flutterwave's real API (`api.flutterwave.com`) and writes into
  the same `flutterwave_subaccounts` table — which, for HoBS, finally makes
  the table name accurate.
- `PAYSTACK_SECRET_KEY` / `PAYSTACK_WEBHOOK_SECRET` env vars → per the
  product decision, these hold the FLUTTERWAVE secret key and webhook hash
  for HoBS specifically, kept unrenamed to avoid touching shared config code.
- `RoomBooking.payment_ref` → stores Flutterwave's `flw_ref` / `tx_ref`.

## Why this matters
Do NOT reuse `PaystackSubaccountService` or `create_paystack_payment_link`
(in `checkout_service.py`) for anything booking-related — both call
Paystack's real API and will silently create real Paystack subaccounts/
transactions instead of Flutterwave ones. HoBS has its own
`FlutterwaveSubaccountService` and `create_flutterwave_payment_link` for
this reason — always use those for bookings.

## Action items
- [x] `flutterwave_subaccount_service.py` — subaccount create/lookup against
      the real Flutterwave API, writing to the existing `FlutterwaveSubaccount` model
- [x] `create_flutterwave_payment_link` — booking payment link generation
- [ ] Booking payment webhook handler validating Flutterwave's `verif-hash`
      header (Phase 6 — not yet built)
