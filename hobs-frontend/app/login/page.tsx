"use client";

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, login } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const { setSession } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await login(email, password);
      setSession({
        access_token: result.access_token,
        merchant_id: result.merchant_id,
        name: result.name,
        email: result.email,
        email_verified: result.email_verified,
        must_change_password: result.must_change_password,
      });

      // Backend-driven routing: a first-login merchant (password set via the
      // token link but never rotated) must change it before anything else;
      // an unverified email is the next gate; otherwise straight to dashboard.
      if (result.must_change_password) {
        // No authenticated "change password" endpoint exists on the
        // backend — the only paths that set a merchant's password are the
        // approval-email token (POST /merchants/set-password) and the
        // email-code reset flow (POST /merchants/reset-password). Since
        // they're already logged in and we know their email, send them
        // straight into the reset-password flow pre-filled.
        router.push(`/forgot-password?email=${encodeURIComponent(result.email)}&reason=must_change`);
      } else if (!result.email_verified) {
        router.push("/verify-email");
      } else {
        router.push("/dashboard");
      }
    } catch (err) {
      if (err instanceof ApiError && err.status === 429) {
        setError("Too many login attempts. Please wait 15 minutes and try again.");
      } else if (err instanceof ApiError) {
        setError(err.message);
      } else {
        setError("Something went wrong. Please try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <h1>Sign in</h1>
      <p className="subtitle">Access your hotel&rsquo;s dashboard.</p>

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
            autoComplete="username"
          />
        </div>

        <div className="field">
          <label htmlFor="password">Password</label>
          <input
            id="password"
            type="password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete="current-password"
          />
        </div>

        <button className="btn" type="submit" disabled={busy}>
          {busy ? "Signing in…" : "Sign in"}
        </button>
      </form>

      <p className="helper-link">
        <Link href="/forgot-password">Forgot your password?</Link>
      </p>
      <p className="helper-link">
        Not onboarded yet? <Link href="/get-started">Apply here</Link>
      </p>
    </main>
  );
}
