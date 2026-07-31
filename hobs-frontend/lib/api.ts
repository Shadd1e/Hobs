/**
 * lib/api.ts
 *
 * Single source of truth for every call this frontend makes to the HoBS
 * backend. Every function here maps 1:1 to a real endpoint that
 * exists in the backend repo (see the file:line reference in each comment)
 * — nothing here is speculative. If a form needs a field that isn't in the
 * matching Pydantic schema on the backend, that's a bug: fix the schema
 * expectation here, don't invent a new backend field.
 *
 * Auth model: bearer JWT, NOT cookies. The token comes back in
 * `access_token` from /merchants/login and must be sent as
 * `Authorization: Bearer <token>` on every authenticated call. See
 * lib/auth.ts for how the token is stored/retrieved client-side.
 *
 * Base prefix: every route below is mounted under API_V1_STR = "/api/v1"
 * (app/core/config.py:8), so this client always prefixes with that — do not
 * hardcode "/api/v1" again in call sites.
 */

const RAW_BASE = process.env.NEXT_PUBLIC_API_BASE_URL;
if (!RAW_BASE && typeof window !== "undefined") {
  // Fail loudly in the browser rather than silently calling a relative path
  // that happens to 404 in a confusing way.
  // eslint-disable-next-line no-console
  console.error(
    "NEXT_PUBLIC_API_BASE_URL is not set. Copy .env.local.example to .env.local."
  );
}
const API_BASE = `${(RAW_BASE ?? "").replace(/\/$/, "")}/api/v1`;

// ──────────────────────────────────────────────────────────────────────────
// Error handling
// ──────────────────────────────────────────────────────────────────────────

/**
 * Every error path in the backend returns FastAPI's default shape:
 *   { "detail": "some string" }               — explicit HTTPException(detail=...)
 *   { "detail": [{ "loc": [...], "msg": ... }] } — pydantic validation (422)
 * This class normalizes both into a single human-readable `message`, while
 * keeping `status` and `raw` around for callers that need to branch on
 * specific codes (e.g. 429 rate limit, 410 gone/expired, 401 needs login).
 */
export class ApiError extends Error {
  status: number;
  raw: unknown;

  constructor(status: number, message: string, raw?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.raw = raw;
  }
}

function extractMessage(body: unknown, fallback: string): string {
  if (body && typeof body === "object" && "detail" in body) {
    const detail = (body as { detail: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail)) {
      return detail
        .map((d) =>
          typeof d === "object" && d && "msg" in d
            ? String((d as { msg: unknown }).msg)
            : JSON.stringify(d)
        )
        .join(" ");
    }
  }
  return fallback;
}

type RequestOptions = {
  token?: string | null;
  signal?: AbortSignal;
};

async function request<T>(
  method: "GET" | "POST" | "PATCH" | "DELETE",
  path: string,
  body?: unknown,
  opts: RequestOptions = {}
): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (opts.token) headers["Authorization"] = `Bearer ${opts.token}`;

  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: opts.signal,
    });
  } catch (networkErr) {
    // fetch() throws on network failure / CORS rejection, not on 4xx/5xx.
    throw new ApiError(
      0,
      "Couldn't reach the server. Check your connection and try again.",
      networkErr
    );
  }

  // Some endpoints (204s aren't used here, but be defensive) return no body.
  const text = await res.text();
  const data = text ? safeJson(text) : null;

  if (!res.ok) {
    const fallback =
      res.status === 429
        ? "Too many attempts. Please wait before trying again."
        : res.status === 410
        ? "This link has expired or was already used."
        : res.status >= 500
        ? "Something went wrong on our end. Please try again."
        : "Request failed.";
    throw new ApiError(res.status, extractMessage(data, fallback), data);
  }

  return data as T;
}

function safeJson(text: string): unknown {
  try {
    return JSON.parse(text);
  } catch {
    return null;
  }
}

// ──────────────────────────────────────────────────────────────────────────
// Onboarding wizard — app/api/v1/merchant.py
// No Authorization header on any of these; the resume_token IS the credential.
// ──────────────────────────────────────────────────────────────────────────

export type ApplyStepOneInput = {
  full_name: string;
  email: string;
  phone_number: string;
  whatsapp_number?: string | null;
  /** Honeypot — render an off-screen input bound to this and never let a
   *  real user see it. Must be sent as empty string/undefined for humans. */
  website?: string;
};

export type ApplyStepOneResult = {
  application_id: string;
  resume_token: string;
  current_step: number;
};

/** POST /merchants/apply/start — merchant.py:888 */
export function applyStepOne(input: ApplyStepOneInput) {
  return request<ApplyStepOneResult>("POST", "/merchants/apply/start", input);
}

export type ApplyStepTwoInput = {
  business_name: string;
  business_type: string;
  city_state: string;
  registration_status: "registered" | "unregistered";
  num_branches: number;
  monthly_order_volume?: string | null;
  uses_whatsapp_manual: boolean;
  uses_delivery_service: boolean;
  heard_about_us?: string | null;
  comments?: string | null;
};

/** PATCH /merchants/apply/resume/{resume_token}/business — merchant.py:1007 */
export function applyStepTwo(resumeToken: string, input: ApplyStepTwoInput) {
  return request<{ current_step: number; registration_status: string }>(
    "PATCH",
    `/merchants/apply/resume/${encodeURIComponent(resumeToken)}/business`,
    input
  );
}

export type ApplyStepThreeInput =
  | { cac_number: string }
  | { verification_method: "bvn"; bvn: string }
  | { verification_method: "nin"; nin: string };

/** PATCH /merchants/apply/resume/{resume_token}/verification — merchant.py:1052
 *  Which shape to send depends on step 2's registration_status:
 *  "registered" -> { cac_number }.  "unregistered" -> bvn OR nin variant. */
export function applyStepThree(resumeToken: string, input: ApplyStepThreeInput) {
  return request<{
    current_step: number;
    verification_status: string;
    transaction_limit: number | null;
  }>(
    "PATCH",
    `/merchants/apply/resume/${encodeURIComponent(resumeToken)}/verification`,
    input
  );
}

/** POST /merchants/apply/resume/{resume_token}/submit — merchant.py:1141 */
export function applyStepFour(resumeToken: string, termsVersion: string) {
  return request<Record<string, unknown>>(
    "POST",
    `/merchants/apply/resume/${encodeURIComponent(resumeToken)}/submit`,
    { terms_version: termsVersion }
  );
}

export type ResumeState = {
  current_step: number;
  full_name: string;
  email: string;
  phone_number: string;
  whatsapp_number: string | null;
  business_name: string | null;
  business_type: string | null;
  city_state: string | null;
  registration_status: "registered" | "unregistered" | null;
  num_branches: number | null;
  monthly_order_volume: string | null;
  uses_whatsapp_manual: boolean;
  uses_delivery_service: boolean;
  heard_about_us: string | null;
  comments: string | null;
  verification_method: "bvn" | "nin" | null;
  verification_status: string | null;
  has_cac_number: boolean;
  has_bvn: boolean;
  has_nin: boolean;
};

/**
 * GET /merchants/apply/resume/{resume_token} — merchant.py:370
 * Call this on EVERY mount of the wizard when a resume_token is present
 * (e.g. from the URL), not just once — the backend comment is explicit that
 * skipping this silently blanks out fields the applicant already filled in.
 * Throws ApiError(404) for a bad token, ApiError(410) if already submitted
 * or the token expired.
 */
export function applyResume(resumeToken: string) {
  return request<ResumeState>(
    "GET",
    `/merchants/apply/resume/${encodeURIComponent(resumeToken)}`
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Set password (from the approval email link) — merchant.py:647
// ──────────────────────────────────────────────────────────────────────────

/** POST /merchants/set-password. Token is single-use, 72h expiry (ApiError 400 on bad/expired/used). */
export function setPassword(token: string, newPassword: string) {
  return request<{ detail: string }>("POST", "/merchants/set-password", {
    token,
    new_password: newPassword,
  });
}

// ──────────────────────────────────────────────────────────────────────────
// Login / session — merchant.py:489
// ──────────────────────────────────────────────────────────────────────────

export type LoginResult = {
  access_token: string;
  token_type: "bearer";
  merchant_id: string;
  name: string;
  email: string;
  email_verified: boolean;
  must_change_password: boolean;
};

/** POST /merchants/login. ApiError(429) on rate limit (Retry-After: 900s), ApiError(401) on bad creds. */
export function login(email: string, password: string) {
  return request<LoginResult>("POST", "/merchants/login", { email, password });
}

/** GET /merchants/me — requires bearer token. */
export function getMe(token: string) {
  return request<{
    id: string;
    name: string;
    email: string;
    email_verified: boolean;
    whatsapp_number: string | null;
  }>("GET", "/merchants/me", undefined, { token });
}

/** POST /merchants/verify-email-code — requires bearer token, 6-digit code. */
export function verifyEmailCode(token: string, code: string) {
  return request<{ detail: string }>(
    "POST",
    "/merchants/verify-email-code",
    { code },
    { token }
  );
}

/** POST /merchants/resend-verification — requires bearer token. */
export function resendVerification(token: string) {
  return request<{ detail: string }>(
    "POST",
    "/merchants/resend-verification",
    undefined,
    { token }
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Forgot / reset password — merchant.py (public, token-based)
// ──────────────────────────────────────────────────────────────────────────

/**
 * POST /merchants/forgot-password — merchant.py:524
 * Always returns 200 with the same generic message whether or not the email
 * exists (anti-enumeration) — do NOT branch UI copy on success vs failure.
 * Sends a 6-digit code via email, 10-minute TTL in Redis.
 */
export function forgotPassword(email: string) {
  return request<{ detail: string }>("POST", "/merchants/forgot-password", {
    email,
  });
}

/**
 * POST /merchants/reset-password — merchant.py:583
 * NOTE: takes email + the 6-digit code from that email, NOT a link token
 * (that's a different flow from /merchants/set-password, which IS
 * token-based). Code is single-use, consumed from Redis on success.
 */
export function resetPassword(email: string, code: string, newPassword: string) {
  return request<{ detail: string }>("POST", "/merchants/reset-password", {
    email,
    code,
    new_password: newPassword,
  });
}

// ──────────────────────────────────────────────────────────────────────────
// Clients (= hotels, in this merchant's account) — app/api/v1/client_api.py
// A merchant can own more than one hotel/client, so the dashboard needs to
// let them pick which one they're managing before anything hotel-scoped
// (rooms, bookings, etc.) can be called — those all take client_id.
// ──────────────────────────────────────────────────────────────────────────

export type ClientSummary = {
  id: string;
  name: string;
  whatsapp_number: string | null;
  created_at: string | null;
};

/** GET /clients/ — requires merchant bearer token. client_api.py:419 */
export function listClients(token: string) {
  return request<ClientSummary[]>("GET", "/clients/", undefined, { token });
}

// ──────────────────────────────────────────────────────────────────────────
// Hotel dashboard — app/api/v1/hotel_dashboard.py, prefix /hotel
// All of these require the merchant bearer token AND a client_id query
// param; the backend re-verifies that client_id actually belongs to the
// authenticated merchant on every call (403 if not) — don't skip sending
// client_id thinking the token alone is enough.
// ──────────────────────────────────────────────────────────────────────────

export type RoomStatusRow = {
  id: string;
  room_number: string;
  room_type_name: string | null;
  room_type_price: number | null;
  is_active: boolean;
  is_booked_today: boolean;
};

/** GET /hotel/dashboard/rooms?client_id=... — hotel_dashboard.py:100 */
export function dashboardRooms(token: string, clientId: string) {
  return request<RoomStatusRow[]>(
    "GET",
    `/hotel/dashboard/rooms?client_id=${encodeURIComponent(clientId)}`,
    undefined,
    { token }
  );
}

export type RoomAdminDetail = {
  room_number: string;
  is_booked_today: boolean;
  booking: {
    guest_name: string | null;
    guest_phone: string | null;
    check_in: string;
    check_out: string;
    nights: number;
    total_amount: number;
    amount_paid: number | null;
    source: "guest_whatsapp" | "staff_whatsapp" | "dashboard";
    logged_by_staff_phone: string | null;
    booking_code: string;
  } | null;
};

/** GET /hotel/dashboard/rooms/{room_id}?client_id=... — hotel_dashboard.py:116 */
export function dashboardRoomDetail(token: string, roomId: string, clientId: string) {
  return request<RoomAdminDetail>(
    "GET",
    `/hotel/dashboard/rooms/${encodeURIComponent(roomId)}?client_id=${encodeURIComponent(clientId)}`,
    undefined,
    { token }
  );
}

// ── Room types ──────────────────────────────────────────────────────────

export type RoomTypeRead = {
  id: string;
  name: string;
  description: string | null;
  price: number;
  image_url: string | null;
  merchant_id: string | null;
  client_id: string | null;
};

export type RoomTypeWriteInput = {
  name: string;
  description?: string | null;
  price: number;
  image_url?: string | null;
};

/**
 * POST /hotel/room-types — hotel_dashboard.py:136. 409 if name already
 * exists for this hotel. merchant_id/client_id are separate args here
 * (not folded into the input object) to match how every dashboard page
 * calls this: they already have both from session + the route/selector.
 */
export function createRoomType(
  token: string,
  clientId: string,
  merchantId: string,
  input: RoomTypeWriteInput
) {
  return request<RoomTypeRead>("POST", "/hotel/room-types", {
    ...input,
    merchant_id: merchantId,
    client_id: clientId,
  }, { token });
}

/** GET /hotel/room-types?client_id=... — hotel_dashboard.py:154 */
export function listRoomTypes(token: string, clientId: string) {
  return request<RoomTypeRead[]>(
    "GET",
    `/hotel/room-types?client_id=${encodeURIComponent(clientId)}`,
    undefined,
    { token }
  );
}

/** PATCH /hotel/room-types/{id}?client_id=... — hotel_dashboard.py:165. This is also the price-adjustment endpoint. */
export function updateRoomType(
  token: string,
  clientId: string,
  roomTypeId: string,
  patch: Partial<RoomTypeWriteInput>
) {
  return request<RoomTypeRead>(
    "PATCH",
    `/hotel/room-types/${encodeURIComponent(roomTypeId)}?client_id=${encodeURIComponent(clientId)}`,
    patch,
    { token }
  );
}

/** DELETE /hotel/room-types/{id}?client_id=... — hotel_dashboard.py:185. 409 if rooms still reference it. */
export function deleteRoomType(token: string, clientId: string, roomTypeId: string) {
  return request<{ status: string }>(
    "DELETE",
    `/hotel/room-types/${encodeURIComponent(roomTypeId)}?client_id=${encodeURIComponent(clientId)}`,
    undefined,
    { token }
  );
}

// ── Rooms ────────────────────────────────────────────────────────────────

export type RoomRead = {
  id: string;
  room_number: string;
  room_type_id: string;
  is_active: boolean;
  merchant_id: string;
  client_id: string;
};

export type RoomWriteInput = {
  room_number: string;
  room_type_id: string;
  is_active?: boolean;
};

/** POST /hotel/rooms — hotel_dashboard.py:207. 409 if room_number already exists for this hotel. */
export function createRoom(
  token: string,
  clientId: string,
  merchantId: string,
  input: RoomWriteInput
) {
  return request<RoomRead>("POST", "/hotel/rooms", {
    ...input,
    merchant_id: merchantId,
    client_id: clientId,
  }, { token });
}

/** GET /hotel/rooms?client_id=... — hotel_dashboard.py:228 */
export function listRooms(token: string, clientId: string) {
  return request<RoomRead[]>(
    "GET",
    `/hotel/rooms?client_id=${encodeURIComponent(clientId)}`,
    undefined,
    { token }
  );
}

/** PATCH /hotel/rooms/{id}?client_id=... — hotel_dashboard.py:239 */
export function updateRoom(
  token: string,
  clientId: string,
  roomId: string,
  patch: Partial<RoomWriteInput>
) {
  return request<RoomRead>(
    "PATCH",
    `/hotel/rooms/${encodeURIComponent(roomId)}?client_id=${encodeURIComponent(clientId)}`,
    patch,
    { token }
  );
}

/** DELETE /hotel/rooms/{id}?client_id=... — hotel_dashboard.py:258 */
export function deleteRoom(token: string, clientId: string, roomId: string) {
  return request<{ status: string }>(
    "DELETE",
    `/hotel/rooms/${encodeURIComponent(roomId)}?client_id=${encodeURIComponent(clientId)}`,
    undefined,
    { token }
  );
}

// ── Bookings ─────────────────────────────────────────────────────────────

export type BookingStatus =
  | "CREATED"
  | "PENDING_PAYMENT"
  | "PAID"
  | "CHECKED_IN"
  | "CHECKED_OUT"
  | "CANCELLED"
  | "REFUNDED";

export type RoomBookingAdminRead = {
  id: string;
  booking_code: string;
  merchant_id: string;
  client_id: string;
  room_id: string;
  guest_name: string | null;
  guest_phone: string | null;
  check_in: string;
  check_out: string;
  total_amount: string;
  amount_paid: string | null;
  status: BookingStatus;
  source: "guest_whatsapp" | "staff_whatsapp" | "dashboard";
  logged_by_staff_phone: string | null;
  raw_staff_message: string | null;
  payment_ref: string | null;
  confirmed_at: string | null;
  checked_in_at: string | null;
  checked_out_at: string | null;
  cancelled_at: string | null;
  created_at: string;
};

/**
 * GET /hotel/bookings?client_id=&status= — hotel_dashboard.py:293
 * NOTE: the backend does a raw `status.upper()` string match against the
 * enum column, NOT a validated enum field — passing anything other than
 * one of the real BookingStatus values (e.g. "PENDING" instead of
 * "PENDING_PAYMENT") silently matches zero rows rather than erroring.
 * Keep any status dropdown's option values exactly equal to BookingStatus.
 */
export function listBookings(token: string, clientId: string, status?: string) {
  const qs = new URLSearchParams({ client_id: clientId });
  if (status) qs.set("status", status);
  return request<RoomBookingAdminRead[]>("GET", `/hotel/bookings?${qs.toString()}`, undefined, {
    token,
  });
}

/**
 * GET /hotel/bookings/{booking_code}?client_id=... — hotel_dashboard.py:277
 * Argument order is (token, clientId, bookingCode) to match every other
 * hotel-scoped call in this file (clientId always right after token).
 */
export function getBooking(token: string, clientId: string, bookingCode: string) {
  return request<RoomBookingAdminRead>(
    "GET",
    `/hotel/bookings/${encodeURIComponent(bookingCode)}?client_id=${encodeURIComponent(clientId)}`,
    undefined,
    { token }
  );
}

// ──────────────────────────────────────────────────────────────────────────
// Hotel STAFF auth — app/api/v1/hotel_staff_auth.py
// Separate credential/token from the merchant login above. This token is
// only valid for the audit-log and role-change endpoints below — it is NOT
// interchangeable with the merchant bearer token used everywhere else on
// this page (get_current_staff decodes a JWT with type:"staff"; the
// merchant token has a different subject/shape and will be rejected here).
// ──────────────────────────────────────────────────────────────────────────

export type StaffLoginResult = {
  access_token: string;
  token_type: "bearer";
  staff_id: string;
  role: string;
  name: string | null;
};

/** POST /hotel/staff/login — hotel_staff_auth.py:41 */
export function staffLogin(phoneNumber: string, password: string) {
  return request<StaffLoginResult>("POST", "/hotel/staff/login", {
    phone_number: phoneNumber,
    password,
  });
}

export type AuditLogEntry = {
  id: string;
  action: string;
  room_id: string | null;
  booking_id: string | null;
  previous_status: string | null;
  new_status: string | null;
  staff_phone: string | null;
  is_high_impact: boolean;
  reviewed: boolean;
  reverted: boolean;
  created_at: string;
  revert_expires_at: string | null;
};

/** GET /hotel/audit-log?client_id=&pending_only= — requires STAFF token. hotel_dashboard.py:316 */
export function listAuditLog(staffToken: string, clientId: string, pendingOnly = false) {
  const qs = new URLSearchParams({ client_id: clientId, pending_only: String(pendingOnly) });
  return request<AuditLogEntry[]>("GET", `/hotel/audit-log?${qs.toString()}`, undefined, {
    token: staffToken,
  });
}

/** POST /hotel/audit-log/{log_id}/revert — requires STAFF token. hotel_dashboard.py:347 */
export function revertAuditLogEntry(staffToken: string, logId: string) {
  return request<{ status: string; log_id: string }>(
    "POST",
    `/hotel/audit-log/${encodeURIComponent(logId)}/revert`,
    undefined,
    { token: staffToken }
  );
}

/**
 * POST /hotel/staff/{target_staff_id}/role-change?new_role=... — requires
 * STAFF token, top_manager only (backend-enforced, not just UI-hidden).
 * hotel_dashboard.py:365. new_role is a query param per the route
 * signature, not a body field.
 */
export function initiateRoleChange(staffToken: string, targetStaffId: string, newRole: string) {
  return request<{ status: string; request_id: string; sent_to: string; expires_at: string }>(
    "POST",
    `/hotel/staff/${encodeURIComponent(targetStaffId)}/role-change?new_role=${encodeURIComponent(newRole)}`,
    undefined,
    { token: staffToken }
  );
}

/** POST /hotel/staff/role-change/{request_id}/confirm?code=... — hotel_dashboard.py:388 */
export function confirmRoleChange(staffToken: string, requestId: string, code: string) {
  return request<{ status: string; staff_id: string; new_role: string }>(
    "POST",
    `/hotel/staff/role-change/${encodeURIComponent(requestId)}/confirm?code=${encodeURIComponent(code)}`,
    undefined,
    { token: staffToken }
  );
}
