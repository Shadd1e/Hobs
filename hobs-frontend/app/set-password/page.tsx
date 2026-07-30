"use client";

/**
 * Backed by POST /merchants/set-password.
 * Reached via the link in the approval email: /set-password?token=<email_verification_token>
 * Token is single-use and expires 72h after the approval email was sent
 * (merchant.py:647-652) — an expired/used token returns 400, not 410, so we
 * surface the raw backend message rather than assuming which case it is.
 */

import { Suspense, useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { ApiError, setPassword } from "@/lib/api";

export default function SetPasswordPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <SetPasswordForm />
    </Suspense>
  );
}

function SetPasswordForm() {
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");

  const [password, setPasswordValue] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);

  if (!token) {
    return (
      <main className="page">
        <h1>Missing link</h1>
        <p className="banner-error">
          This page needs the link from your approval email — the token is
          missing from the URL.
        </p>
      </main>
    );
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);

    if (password.length < 8) {
      setError("Password must be at least 8 characters.");
      return;
    }
    if (password !== confirm) {
      setError("Passwords don't match.");
      return;
    }

    setBusy(true);
    try {
      await setPassword(token as string, password);
      setDone(true);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  if (done) {
    return (
      <main className="page">
        <h1>Password set</h1>
        <p className="subtitle">You can now sign in with your new password.</p>
        <button className="btn" onClick={() => router.push("/login")}>
          Go to sign in
        </button>
      </main>
    );
  }

  return (
    <main className="page">
      <h1>Set your password</h1>
      <p className="subtitle">Choose a password to finish setting up your account.</p>

      <form onSubmit={handleSubmit}>
        {error && <div className="banner-error">{error}</div>}

        <div className="field">
          <label htmlFor="password">New password</label>
          <input
            id="password"
            type="password"
            required
            value={password}
            onChange={(e) => setPasswordValue(e.target.value)}
            autoComplete="new-password"
          />
          <div className="field-hint">At least 8 characters.</div>
        </div>

        <div className="field">
          <label htmlFor="confirm">Confirm password</label>
          <input
            id="confirm"
            type="password"
            required
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            autoComplete="new-password"
          />
        </div>

        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Saving…" : "Set password"}
        </button>
      </form>

      <p className="helper-link">
        <Link href="/login">Back to sign in</Link>
      </p>
    </main>
  );
}
