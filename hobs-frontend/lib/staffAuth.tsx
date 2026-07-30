"use client";

/**
 * lib/staffAuth.tsx
 *
 * Separate from lib/auth.tsx on purpose. POST /hotel/staff/login issues a
 * JWT with `type: "staff"` (see app/api/v1/hotel_dashboard.py's
 * get_current_staff), which is a DIFFERENT credential from the merchant
 * bearer token — it identifies an individual HotelStaff row, not the
 * merchant account. The audit-log and role-change endpoints require this
 * token specifically; sending the merchant token there 401s.
 *
 * A dashboard user needs BOTH sessions to see everything: the merchant
 * session to view rooms/bookings/room-types, and (optionally) a staff
 * session to view the audit log and manage staff roles. Not every merchant
 * user will have a HotelStaff row, so this session is allowed to be absent
 * — pages that need it should prompt for staff login rather than assuming
 * it exists alongside the merchant session.
 */

import {
  createContext,
  useCallback,
  useContext,
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
  setStaffSession: (session: StaffSession | null) => void;
  staffLogout: () => void;
};

const StaffAuthContext = createContext<StaffAuthContextValue | null>(null);

function readInitial(): StaffSession | null {
  if (typeof window === "undefined") return null;
  const raw = window.localStorage.getItem(STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as StaffSession;
  } catch {
    return null;
  }
}

export function StaffAuthProvider({ children }: { children: ReactNode }) {
  const [staffSession, setStaffSessionState] = useState<StaffSession | null>(readInitial);

  const setStaffSession = useCallback((next: StaffSession | null) => {
    setStaffSessionState(next);
    if (typeof window === "undefined") return;
    if (next) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const staffLogout = useCallback(() => setStaffSession(null), [setStaffSession]);

  const value = useMemo(
    () => ({ staffSession, setStaffSession, staffLogout }),
    [staffSession, setStaffSession, staffLogout]
  );

  return <StaffAuthContext.Provider value={value}>{children}</StaffAuthContext.Provider>;
}

export function useStaffAuth(): StaffAuthContextValue {
  const ctx = useContext(StaffAuthContext);
  if (!ctx) throw new Error("useStaffAuth must be used within <StaffAuthProvider>");
  return ctx;
}
