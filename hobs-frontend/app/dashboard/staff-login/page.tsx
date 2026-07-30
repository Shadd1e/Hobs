"use client";

/**
 * POST /hotel/staff/login — hotel_staff_auth.py. Phone + password for an
 * individual HotelStaff row. Deliberately separate from merchant login
 * (see lib/staffAuth.tsx) — needed for the audit log / role-change pages,
 * which check WHICH staff member is acting, not just which merchant
 * account owns the hotel.
 */

import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ApiError, staffLogin } from "@/lib/api";
import { useStaffAuth } from "@/lib/staffAuth";

export default function StaffLoginPage() {
  const router = useRouter();
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
      router.push("/dashboard/audit-log");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Please try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="page">
      <h1>Staff sign in</h1>
      <p className="subtitle">
        For the audit log and role changes. This is separate from the hotel account login — sign in with
        the phone number and password registered for your staff account.
      </p>

      <form onSubmit={handleSubmit}>
        {error && <div className="banner-error">{error}</div>}

        <div className="field">
          <label htmlFor="phone">Phone number</label>
          <input
            id="phone"
            required
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="2348012345678"
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
        <Link href="/dashboard">Back to dashboard</Link>
      </p>
      <p className="dash-hint" style={{ textAlign: "center", marginTop: 8 }}>
        No self-service password reset yet for staff accounts — ask a top manager to set or reset it.
      </p>
    </main>
  );
}
