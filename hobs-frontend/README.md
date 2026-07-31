# HoBS frontend — homepage / onboarding / login / hotel dashboard

Next.js (App Router, TypeScript) frontend for the merchant/hotel-owner side
of HoBS.

## Setup

```bash
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_BASE_URL to your backend
npm run dev
```

## Structure

1. **Public funnel**: homepage → 4-step apply wizard → admin approval
   (offline) → set password → sign in → email verification gate.
2. **Hotel dashboard** (`/dashboard`): a single shared top bar
   (`components/DashboardChrome.tsx`) with a hotel-switcher dropdown and
   tabs — Rooms (`/dashboard`), Room types, Manage rooms, Bookings, Audit
   log. Which hotel is selected lives in the `?client=` query string
   (persisted to `localStorage` as a fallback so returning to `/dashboard`
   with no query string re-selects the last one) via
   `components/useDashboardClient.ts` — every dashboard page uses that hook
   rather than re-implementing the client-selection/auth-guard logic.
3. **Staff audit log** (`/dashboard/audit-log`) requires a *separate* staff
   credential from `/dashboard/staff-login` (`lib/staffAuth.tsx`) — not the
   merchant login. Includes revert and a top_manager-only role-change panel
   (email-code confirmed, never over WhatsApp).

## How this maps to the backend

Every backend call lives in **`lib/api.ts`** — every function has a
comment pointing at the backend file/line it was read from. Convention:
every hotel-scoped function takes `clientId` as its second argument, right
after `token`, so call sites read consistently
(`fn(token, clientId, ...)`).

Key contract details worth knowing before extending this:

- **Auth is bearer JWT, not cookies** (`lib/auth.tsx`). No cookie-based
  session exists anywhere in this backend.
- **The apply wizard's `resume_token` IS the credential** for steps 2-4 —
  refetch `GET /merchants/apply/resume/{token}` on every mount.
- **Two unrelated "reset password" mechanisms**: `POST
  /merchants/set-password` (approval-email token, first-time only) vs
  `POST /merchants/reset-password` (email + 6-digit code, also used for
  the post-login `must_change_password` case since there's no separate
  authenticated change-password endpoint).
- **A merchant can own more than one hotel** — `GET /clients/` lists them;
  every `/hotel/*` call needs `client_id`, re-verified server-side (403 if
  it doesn't belong to the authenticated merchant).
- **`GET /hotel/bookings` does a raw `status.upper()` string match, not a
  validated enum field.** A status filter value that isn't exactly one of
  `CREATED | PENDING_PAYMENT | PAID | CHECKED_IN | CHECKED_OUT | CANCELLED
  | REFUNDED` silently matches zero rows instead of erroring — keep any
  status dropdown's values exactly equal to that list.
- **The staff audit log uses a second, unrelated credential** — token from
  `POST /hotel/staff/login` (phone + password), rejected by the merchant
  JWT (`get_current_staff` checks `payload.type == "staff"`). No `GET
  /hotel/staff/me` exists, so an expired staff token is only caught when a
  real call 401s.
- **CORS**: production backend rejects wildcard origins — add the deployed
  origin to the backend's `ALLOWED_ORIGINS` or requests fail silently in
  the browser.

## Repair log (this pass)

This zip was uploaded mid-migration and would not compile. Fixed:

- `lib/api.ts` still had the old contract (`Room`/`RoomType`/`BookingAdmin`
  types, old argument orders) while every dashboard page had already been
  rewritten against a new one (`RoomRead`/`RoomTypeRead`/
  `RoomBookingAdminRead`, `clientId` right after `token` everywhere,
  `getBooking(token, clientId, bookingCode)`). Rewrote `lib/api.ts` to
  match what the pages actually call.
- `/dashboard` (root) was still the old picker-that-redirects-to
  `/dashboard/{clientId}` page — never migrated to the new chrome/hook
  pattern, even though `DashboardChrome`'s "Rooms" tab already pointed at
  it. Rebuilt it as the room-status grid + guest-detail drill-down.
- Deleted the orphaned `app/dashboard/[clientId]/*` tree and the orphaned
  top-level `app/staff-login/page.tsx` — both fully superseded and
  unreferenced by anything in the current flow.
- `app/globals.css` had zero of the `.dash-*` / `.btn-link` / `.status-pill`
  / `.room-card` classes the new chrome and pages render with — added all
  of them.
- Fixed a silent bug in the bookings status filter: it offered `"PENDING"`
  as an option, but the real enum value is `"PENDING_PAYMENT"` — given the
  raw-string-match backend behavior above, that filter always returned
  zero rows.
- Fixed `useDashboardClient`'s `selectClient` to push `${pathname}?...`
  instead of a bare `?...` — the latter isn't guaranteed to resolve against
  the current route consistently.

## Known gaps / next phase

- **Guest-facing booking chat is WhatsApp-only** — no REST/web-chat
  endpoint for guests exists yet (`POST /api/v1/webhook/hotel-whatsapp` is
  a Meta webhook). A guest-facing web widget needs new backend endpoints.
- **Payments use Flutterwave, not Paystack**, despite `Paystack*`-named
  config/services in the codebase for the unrelated e-commerce product.
  Nothing in this dashboard triggers a payment yet, but get this right
  before building checkout/refund UI — see the backend's
  `docs/WIRING_NOTES.md`.
- No pagination on rooms/room-types/bookings lists yet — fine for now, but
  worth checking before a hotel with hundreds of rooms hits this.
- `app/terms/page.tsx` is a placeholder — needs real copy before launch.
- **Staff creation** (adding a brand-new staff member, distinct from
  changing an existing one's role) doesn't have a wired endpoint — confirm
  with the backend team whether one exists before assuming it doesn't.
