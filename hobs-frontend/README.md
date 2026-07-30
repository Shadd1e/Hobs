# HoBS frontend — homepage / onboarding / login

Next.js (App Router, TypeScript) frontend for the merchant/hotel-owner side
of HoBS. Scope of this pass: homepage → 4-step apply wizard → admin
approval (offline) → set password → sign in → email verification gate →
dashboard placeholder. The real dashboard (rooms, bookings, staff audit) is
the next phase.

## Setup

```bash
npm install
cp .env.local.example .env.local   # set NEXT_PUBLIC_API_BASE_URL to your backend
npm run dev
```

This sandbox has no network access, so `npm install` hasn't been run here —
do it in your own environment. Nothing else needs configuring beyond the
env var.

## How this maps to the backend

Every backend call lives in **`lib/api.ts`** — that file is the single
source of truth for request/response shapes, and every function has a
comment pointing at the backend file/line it was read from. If a page needs
a new field, add it there first and confirm it against the backend schema,
don't guess it in a component.

Key contract details worth knowing before extending this:

- **Auth is bearer JWT, not cookies.** Token comes from `POST
  /merchants/login`, stored in `localStorage` via `lib/auth.tsx`, sent as
  `Authorization: Bearer <token>`. The backend's `TenantMiddleware` reads
  that header — there is no cookie-based session anywhere in this backend.
- **The apply wizard's `resume_token` IS the credential** for steps 2-4 —
  no Authorization header on those calls. Treat it like a bearer token in
  the URL: don't log it, and refetch `GET
  /merchants/apply/resume/{token}` on every mount so a reload doesn't lose
  data (the backend comment is explicit about this).
- **Two different "reset password" mechanisms, don't conflate them:**
  - `POST /merchants/set-password` — token from the *approval* email,
    single-use, 72h expiry. First-time password only.
  - `POST /merchants/reset-password` — email + 6-digit code (10 min TTL,
    sent by `/merchants/forgot-password`). Used both for genuine "forgot
    password" and for the `must_change_password` flag after login, since
    there's no separate authenticated change-password endpoint.
- **Legacy `/merchants/apply` (single-step) is intentionally not wired.**
  The 4-step wizard is the maintained path (see the confirmation message in
  chat for why). If that turns out to be wrong, swap `applyStepOne` calls
  for `applyStepOne`'s sibling in `lib/api.ts` — not written yet, add it
  the same way as the others if needed.
- **CORS**: production backend rejects wildcard origins — whoever deploys
  this needs to add its exact origin to the backend's `ALLOWED_ORIGINS`
  env var, or every request will fail at the browser level with a CORS
  error that looks like nothing happened.

## Known gaps / next phase

- **Guest-facing booking chat is WhatsApp-only in this backend** — there's
  no REST/web-chat endpoint for guests today (`POST
  /api/v1/webhook/hotel-whatsapp` is a Meta webhook, not something a
  browser can call). If a web chat widget for guests is wanted later, that
  needs new backend endpoints first.
- **Hotel dashboard proper** (`/api/v1/hotel/*` — rooms, room types,
  bookings, audit log) uses the *same* merchant JWT from this login flow,
  plus a second, separate staff-level JWT from `POST
  /hotel/staff/login` for the audit-log/role-change endpoints specifically.
  Not built yet — flagging so it's not a surprise when that phase starts.
- **Payments use Flutterwave, not Paystack**, despite `Paystack*`-named
  config/services still existing in the codebase for the unrelated
  e-commerce product. Not relevant to this phase, but critical once
  checkout/payment UI gets built — see the backend's
  `docs/WIRING_NOTES.md`.
- `app/terms/page.tsx` is a placeholder — needs real copy before launch.
