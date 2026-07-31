"use client";

/**
 * lib/staffAuth.tsx
 *
 * The audit-log/role-change endpoints (POST /hotel/staff/login and
 * everything under GET/POST /hotel/audit-log, /hotel/staff/*) require a
 * SEPARATE staff-scoped JWT — not the merchant token from lib/auth.tsx.
 * See hotel_dashboard.py's get_current_staff: it decodes a JWT and rejects
 * anything where payload.type != "staff", so passing the merchant token
 * here will always 401.
 *
 * There's no GET /hotel/staff/me on the backend to validate a stored token
 * on page load, so unlike the merchant session, this one is trusted at
 * face value until an actual API call proves it invalid (at which point
 * callers should clear it and redirect to /staff-login).
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";

const STORAGE_KEY = "hobs_staff_session";

export type StaffSession = {
  access_token: string;
  staff_id: string;
  role: string;
  name: string | null;
};

type StaffAuthContextValue = {
  staffSession: StaffSession | null;
  loading: boolean;
  setStaffSession: (session: StaffSession | null) => void;
  staffLogout: () => void;
};

const StaffAuthContext = createContext<StaffAuthContextValue | null>(null);

export function StaffAuthProvider({ children }: { children: ReactNode }) {
  const [staffSession, setStaffSessionState] = useState<StaffSession | null>(null);
  const [loading, setLoading] = useState(true);

  const setStaffSession = useCallback((next: StaffSession | null) => {
    setStaffSessionState(next);
    if (typeof window === "undefined") return;
    if (next) window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    else window.localStorage.removeItem(STORAGE_KEY);
  }, []);

  const staffLogout = useCallback(() => setStaffSession(null), [setStaffSession]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (raw) {
      try {
        setStaffSessionState(JSON.parse(raw));
      } catch {
        window.localStorage.removeItem(STORAGE_KEY);
      }
    }
    setLoading(false);
  }, []);

  const value = useMemo(
    () => ({ staffSession, loading, setStaffSession, staffLogout }),
    [staffSession, loading, setStaffSession, staffLogout]
  );

  return <StaffAuthContext.Provider value={value}>{children}</StaffAuthContext.Provider>;
}

export function useStaffAuth(): StaffAuthContextValue {
  const ctx = useContext(StaffAuthContext);
  if (!ctx) throw new Error("useStaffAuth must be used within <StaffAuthProvider>");
  return ctx;
}
