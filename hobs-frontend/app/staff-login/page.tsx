"use client";

/**
 * POST /hotel/staff/login. This is a DIFFERENT credential from the
 * merchant login on /login — see lib/staffAuth.tsx for why. A merchant
 * owner may also be enrolled as staff (e.g. top_manager role) with their
 * own phone_number/password separate from their email/password merchant
 * login; this page doesn't assume any relationship between the two.
 */

import { useState, type FormEvent } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense } from "react";
import { ApiError, staffLogin } from "@/lib/api";
import { useStaffAuth } from "@/lib/staffAuth";

export default function StaffLoginPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <StaffLoginForm />
    </Suspense>
  );
}

function StaffLoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { setStaffSession } = useStaffAuth();

  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const result = await staffLogin(phone, password);
      setStaffSession({
        access_token: result.access_token,
        staff_id: result.staff_id,
        role: result.role,
        name: result.name,
      });
      const returnTo = searchParams.get("returnTo");
      router.push(returnTo || "/dashboard");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <h1>Staff sign in</h1>
      <p className="subtitle">
        Separate from the hotel owner login — used for the staff audit log
        and role management.
      </p>

      <form onSubmit={handleSubmit}>
        {error && <div className="banner-error">{error}</div>}

        <div className="field">
          <label htmlFor="phone">Phone number</label>
          <input id="phone" required value={phone} onChange={(e) => setPhone(e.target.value)} />
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
    </main>
  );
}
