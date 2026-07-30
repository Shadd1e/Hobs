"use client";

import { type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import type { ClientSummary } from "@/lib/api";

const TABS = [
  { href: "/dashboard", label: "Rooms" },
  { href: "/dashboard/room-types", label: "Room types" },
  { href: "/dashboard/rooms", label: "Manage rooms" },
  { href: "/dashboard/bookings", label: "Bookings" },
  { href: "/dashboard/audit-log", label: "Audit log" },
];

type Props = {
  merchantName: string;
  clients: ClientSummary[] | null;
  loadingClients: boolean;
  clientsError: string | null;
  clientId: string | null;
  selectClient: (id: string) => void;
  children: ReactNode;
};

export function DashboardChrome({
  merchantName,
  clients,
  loadingClients,
  clientsError,
  clientId,
  selectClient,
  children,
}: Props) {
  const pathname = usePathname();
  const router = useRouter();
  const params = useSearchParams();
  const { logout } = useAuth();

  function tabHref(base: string) {
    if (!clientId) return base;
    const next = new URLSearchParams(Array.from(params.entries()));
    next.set("client", clientId);
    return `${base}?${next.toString()}`;
  }

  return (
    <div className="dash">
      <header className="dash-header">
        <div className="dash-header-top">
          <span className="dash-brand">HoBS</span>
          <div className="dash-header-actions">
            <span className="dash-merchant">{merchantName}</span>
            <button
              className="btn-secondary btn dash-signout"
              onClick={() => {
                logout();
                router.push("/login");
              }}
            >
              Sign out
            </button>
          </div>
        </div>

        {loadingClients ? (
          <p className="dash-hint">Loading your hotels&hellip;</p>
        ) : clientsError ? (
          <div className="banner-error">{clientsError}</div>
        ) : clients && clients.length === 0 ? (
          <p className="dash-hint">
            No hotels on this account yet. A hotel (client) is created as part of onboarding.
          </p>
        ) : clients && clients.length > 0 ? (
          <div className="dash-client-picker">
            <label htmlFor="hotel-select">Hotel</label>
            <select
              id="hotel-select"
              value={clientId ?? ""}
              onChange={(e) => selectClient(e.target.value)}
            >
              <option value="" disabled>
                Select a hotel&hellip;
              </option>
              {clients.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </div>
        ) : null}

        <nav className="dash-nav">
          {TABS.map((tab) => (
            <Link
              key={tab.href}
              href={tabHref(tab.href)}
              className={`dash-tab${pathname === tab.href ? " active" : ""}`}
            >
              {tab.label}
            </Link>
          ))}
        </nav>
      </header>

      <main className="dash-content">
        {clients && clients.length > 0 && !clientId ? (
          <p className="dash-hint">Pick a hotel above to get started.</p>
        ) : (
          children
        )}
      </main>
    </div>
  );
}
