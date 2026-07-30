"use client";

/**
 * Placeholder — the real dashboard (rooms, bookings, staff audit log) is
 * the next phase, wired to /api/v1/hotel/*. This page's only job right now
 * is to prove the auth funnel actually lands somewhere real: guarded by
 * session presence, redirects to /login if missing, redirects to
 * /verify-email if the gate hasn't been cleared.
 */

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function DashboardPage() {
  const router = useRouter();
  const { session, loading, logout } = useAuth();

  useEffect(() => {
    if (loading) return;
    if (!session) {
      router.replace("/login");
    } else if (!session.email_verified) {
      router.replace("/verify-email");
    }
  }, [loading, session, router]);

  if (loading || !session || !session.email_verified) {
    return <main className="page">Loading&hellip;</main>;
  }

  return (
    <main className="page">
      <h1>Welcome, {session.name}</h1>
      <p className="subtitle">
        You&rsquo;re signed in as {session.email}. Room and booking management
        lands here in the next phase.
      </p>
      <button
        className="btn btn-secondary"
        onClick={() => {
          logout();
          router.push("/login");
        }}
      >
        Sign out
      </button>
    </main>
  );
}
