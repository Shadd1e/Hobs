"use client";

import Link from "next/link";
import { usePathname, useParams, useRouter } from "next/navigation";
import { useAuth, useRequireMerchant } from "@/lib/auth";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const session = useRequireMerchant();
  const { logout } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const params = useParams<{ clientId: string }>();
  const clientId = params.clientId;

  if (!session) return <main className="page-wide">Loading&hellip;</main>;

  const base = `/dashboard/${clientId}`;
  const tabs: Array<[string, string]> = [
    [base, "Rooms"],
    [`${base}/room-types`, "Room types"],
    [`${base}/rooms-manage`, "Manage rooms"],
    [`${base}/bookings`, "Bookings"],
    [`${base}/audit-log`, "Staff audit log"],
  ];

  return (
    <div className="page-wide">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          marginBottom: 8,
        }}
      >
        <Link href="/dashboard" style={{ fontSize: "0.85rem" }}>
          &larr; All hotels
        </Link>
        <button
          className="btn-secondary btn"
          style={{ width: "auto", padding: "6px 12px" }}
          onClick={() => {
            logout();
            router.push("/login");
          }}
        >
          Sign out
        </button>
      </div>

      <nav
        style={{
          display: "flex",
          gap: 4,
          borderBottom: "1px solid var(--line)",
          marginBottom: 24,
          flexWrap: "wrap",
        }}
      >
        {tabs.map(([href, label]) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              style={{
                padding: "8px 12px",
                fontSize: "0.9rem",
                color: active ? "var(--ink)" : "var(--muted)",
                borderBottom: active ? "2px solid var(--ink)" : "2px solid transparent",
                textDecoration: "none",
              }}
            >
              {label}
            </Link>
          );
        })}
      </nav>

      {children}
    </div>
  );
}
