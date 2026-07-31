"use client";

/**
 * Every /dashboard/* page needs the same three things: a confirmed merchant
 * session, the list of hotels (clients) that merchant owns, and which one
 * is currently selected. This hook does all three so pages don't repeat
 * the auth-guard/fetch/redirect boilerplate.
 *
 * Selection persistence: the selected client_id lives in the URL
 * (?client=...) so links between dashboard pages carry it forward, with a
 * localStorage fallback ("hobs_last_client") so landing on /dashboard
 * fresh (no query string) re-selects whatever hotel was last used instead
 * of forcing a re-pick every time.
 */

import { useEffect, useMemo, useState } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { ApiError, listClients, type ClientSummary } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const LAST_CLIENT_KEY = "hobs_last_client";

export function useDashboardClient() {
  const router = useRouter();
  const pathname = usePathname();
  const params = useSearchParams();
  const { session, loading: authLoading } = useAuth();

  const [clients, setClients] = useState<ClientSummary[] | null>(null);
  const [clientsError, setClientsError] = useState<string | null>(null);
  const [loadingClients, setLoadingClients] = useState(true);

  // Auth guard — same pattern as the existing dashboard placeholder.
  useEffect(() => {
    if (authLoading) return;
    if (!session) {
      router.replace("/login");
    } else if (!session.email_verified) {
      router.replace("/verify-email");
    }
  }, [authLoading, session, router]);

  // Load the merchant's hotels once we have a confirmed session.
  useEffect(() => {
    if (!session || !session.email_verified) return;
    let cancelled = false;
    setLoadingClients(true);
    setClientsError(null);
    listClients(session.access_token)
      .then((result) => {
        if (cancelled) return;
        setClients(result);
      })
      .catch((err) => {
        if (cancelled) return;
        setClientsError(err instanceof ApiError ? err.message : "Couldn't load your hotels.");
      })
      .finally(() => {
        if (!cancelled) setLoadingClients(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session]);

  const urlClientId = params.get("client");
  const clientId = useMemo(() => {
    if (urlClientId) return urlClientId;
    if (typeof window === "undefined") return null;
    return window.localStorage.getItem(LAST_CLIENT_KEY);
  }, [urlClientId]);

  function selectClient(id: string) {
    if (typeof window !== "undefined") {
      window.localStorage.setItem(LAST_CLIENT_KEY, id);
    }
    const next = new URLSearchParams(Array.from(params.entries()));
    next.set("client", id);
    router.push(`${pathname}?${next.toString()}`);
  }

  const selectedClient = clients?.find((c) => c.id === clientId) ?? null;

  return {
    session,
    authLoading,
    clients,
    clientsError,
    loadingClients,
    clientId,
    selectedClient,
    selectClient,
  };
}
