"use client";

/**
 * Step 1 of the reset-password flow: POST /merchants/forgot-password.
 * Also reused as the "must change password after first login" entry point
 * (see app/login/page.tsx) — same underlying mechanism, since the backend
 * has no separate authenticated change-password endpoint.
 *
 * Important: this endpoint always returns 200 with the same generic
 * message whether or not the email is registered (anti-enumeration). Don't
 * add UI branching that would leak which is which.
 */

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ApiError, forgotPassword } from "@/lib/api";

export default function ForgotPasswordPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <ForgotPasswordForm />
    </Suspense>
  );
}

function ForgotPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const mustChange = params.get("reason") === "must_change";

  const [email, setEmail] = useState(params.get("email") ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await forgotPassword(email);
      setSent(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (sent) {
    return (
      <main className="page">
        <h1>Check your email</h1>
        <p className="subtitle">
          If <strong>{email}</strong> is registered, we&rsquo;ve sent a
          6-digit code. It expires in 10 minutes.
        </p>
        <button
          className="btn"
          onClick={() => router.push(`/reset-password?email=${encodeURIComponent(email)}`)}
        >
          I have my code
        </button>
      </main>
    );
  }

  return (
    <main className="page">
      <h1>{mustChange ? "Set a new password" : "Forgot your password?"}</h1>
      <p className="subtitle">
        {mustChange
          ? "Your account needs a password change before continuing. We'll email you a code."
          : "Enter your email and we'll send you a reset code."}
      </p>

      <form onSubmit={handleSubmit}>
        {error && <div className="banner-error">{error}</div>}

        <div className="field">
          <label htmlFor="email">Email</label>
          <input
            id="email"
            type="email"
            required
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </div>

        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Sending…" : "Send code"}
        </button>
      </form>

      <p className="helper-link">
        <Link href="/login">Back to sign in</Link>
      </p>
    </main>
  );
}
