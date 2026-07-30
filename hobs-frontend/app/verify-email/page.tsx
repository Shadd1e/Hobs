"use client";

/**
 * POST /merchants/verify-email-code — requires bearer token, 6-digit code.
 * Also wires POST /merchants/resend-verification for a "resend" action.
 * Reached when POST /merchants/login returns email_verified: false.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { ApiError, resendVerification, verifyEmailCode } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function VerifyEmailPage() {
  const router = useRouter();
  const { session, loading, setSession } = useAuth();

  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [resending, setResending] = useState(false);

  useEffect(() => {
    if (!loading && !session) router.replace("/login");
  }, [loading, session, router]);

  if (loading || !session) return <main className="page">Loading&hellip;</main>;

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    if (!/^\d{6}$/.test(code)) {
      setError("Enter the 6-digit code from your email.");
      return;
    }
    setBusy(true);
    try {
      await verifyEmailCode(session!.access_token, code);
      setSession({ ...session!, email_verified: true });
      router.push("/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  async function handleResend() {
    setError(null);
    setInfo(null);
    setResending(true);
    try {
      await resendVerification(session!.access_token);
      setInfo("A new code has been sent to your email.");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't resend the code.");
    } finally {
      setResending(false);
    }
  }

  return (
    <main className="page">
      <h1>Verify your email</h1>
      <p className="subtitle">
        Enter the 6-digit code we sent to <strong>{session.email}</strong>.
      </p>

      <form onSubmit={handleSubmit}>
        {error && <div className="banner-error">{error}</div>}
        {info && <div className="banner-info">{info}</div>}

        <div className="field">
          <label htmlFor="code">Verification code</label>
          <input
            id="code"
            required
            inputMode="numeric"
            maxLength={6}
            value={code}
            onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
          />
        </div>

        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Verifying…" : "Verify"}
        </button>
      </form>

      <p className="helper-link">
        <button
          className="btn-secondary btn"
          type="button"
          onClick={handleResend}
          disabled={resending}
          style={{ marginTop: 12 }}
        >
          {resending ? "Sending…" : "Resend code"}
        </button>
      </p>
    </main>
  );
}
