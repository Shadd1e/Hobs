"use client";

/**
 * lib/auth.tsx
 *
 * The backend issues a bearer JWT from POST /merchants/login and expects it
 * back as `Authorization: Bearer <token>` (see app/core/tenant.py's
 * TenantMiddleware, which is what populates request.state.merchant_id that
 * every dashboard/onboarding-me route depends on). There is no cookie-based
 * session anywhere in this backend — don't add one on the frontend either,
 * or requests will silently come back 401 despite a "logged in" UI state.
 *
 * Storage: localStorage. Simple, works across tabs is out of scope for now;
 * swap this module out later if httpOnly-cookie sessions get added
 * server-side, but don't do it unilaterally on the frontend — the backend
 * doesn't read cookies today.
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
import { getMe } from "./api";

const STORAGE_KEY = "hobs_merchant_session";

export type MerchantSession = {
  access_token: string;
  merchant_id: string;
  name: string;
  email: string;
  email_verified: boolean;
  must_change_password: boolean;
};

type AuthContextValue = {
  session: MerchantSession | null;
  /** True until the initial localStorage/getMe check has resolved. */
  loading: boolean;
  setSession: (session: MerchantSession | null) => void;
  logout: () => void;
  /** Re-fetches /merchants/me to refresh email_verified etc. */
  refresh: () => Promise<void>;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSessionState] = useState<MerchantSession | null>(null);
  const [loading, setLoading] = useState(true);

  const setSession = useCallback((next: MerchantSession | null) => {
    setSessionState(next);
    if (typeof window === "undefined") return;
    if (next) {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    } else {
      window.localStorage.removeItem(STORAGE_KEY);
    }
  }, []);

  const logout = useCallback(() => setSession(null), [setSession]);

  const refresh = useCallback(async () => {
    if (!session) return;
    try {
      const me = await getMe(session.access_token);
      setSession({ ...session, email_verified: me.email_verified });
    } catch {
      // Token expired/invalid — drop the session so guarded pages redirect to /login.
      setSession(null);
    }
  }, [session, setSession]);

  // On mount: hydrate from localStorage, then verify the token still works
  // by hitting /merchants/me (a stale/expired token in storage shouldn't
  // silently pretend the user is logged in).
  useEffect(() => {
    if (typeof window === "undefined") return;
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      setLoading(false);
      return;
    }
    try {
      const parsed = JSON.parse(raw) as MerchantSession;
      getMe(parsed.access_token)
        .then((me) => {
          setSessionState({ ...parsed, email_verified: me.email_verified });
        })
        .catch(() => {
          window.localStorage.removeItem(STORAGE_KEY);
          setSessionState(null);
        })
        .finally(() => setLoading(false));
    } catch {
      window.localStorage.removeItem(STORAGE_KEY);
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const value = useMemo(
    () => ({ session, loading, setSession, logout, refresh }),
    [session, loading, setSession, logout, refresh]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within <AuthProvider>");
  return ctx;
}
