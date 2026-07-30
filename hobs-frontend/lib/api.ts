/**
 * lib/api.ts
 *
 * Single source of truth for every call this frontend makes to the HoBS /
 * ShopprHQ backend. Every function here maps 1:1 to a real endpoint that
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
