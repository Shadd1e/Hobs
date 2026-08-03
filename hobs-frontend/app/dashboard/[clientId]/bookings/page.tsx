"use client";

/** GET /hotel/bookings?client_id=&status= */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ApiError, listBookings, type RoomBookingAdminRead, type BookingStatus } from "@/lib/api";
import { useAuth } from "@/lib/auth";

const STATUSES: BookingStatus[] = [
  "CREATED",
  "PENDING_PAYMENT",
  "PAID",
  "CHECKED_IN",
  "CHECKED_OUT",
  "CANCELLED",
  "REFUNDED",
];

export default function BookingsPage() {
  const { session } = useAuth();
  const params = useParams<{ clientId: string }>();
  const clientId = params.clientId;

  const [bookings, setBookings] = useState<RoomBookingAdminRead[] | null>(null);
  const [status, setStatus] = useState<BookingStatus | "">("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    setError(null);
    setBookings(null);
    listBookings(session.access_token, clientId, status || undefined)
      .then(setBookings)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load bookings."));
  }, [session, clientId, status]);

  if (!session) return null;

  return (
    <div>
      <h1>Bookings</h1>

      <div className="field" style={{ maxWidth: 220 }}>
        <label>Filter by status</label>
        <select value={status} onChange={(e) => setStatus(e.target.value as BookingStatus | "")}>
          <option value="">All</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="banner-error">{error}</div>}
      {!error && bookings === null && <p>Loading&hellip;</p>}
      {bookings !== null && bookings.length === 0 && <p className="subtitle">No bookings found.</p>}

      {bookings && bookings.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid var(--line)" }}>
              <th style={{ padding: "8px 4px" }}>Code</th>
              <th style={{ padding: "8px 4px" }}>Guest</th>
              <th style={{ padding: "8px 4px" }}>Dates</th>
              <th style={{ padding: "8px 4px" }}>Status</th>
              <th style={{ padding: "8px 4px" }}>Total</th>
            </tr>
          </thead>
          <tbody>
            {bookings.map((b) => (
              <tr key={b.id} style={{ borderBottom: "1px solid var(--line)" }}>
                <td style={{ padding: "8px 4px" }}>
                  <Link href={`/dashboard/${clientId}/bookings/${b.booking_code}`}>{b.booking_code}</Link>
                </td>
                <td style={{ padding: "8px 4px" }}>{b.guest_name ?? "—"}</td>
                <td style={{ padding: "8px 4px" }}>
                  {b.check_in} → {b.check_out}
                </td>
                <td style={{ padding: "8px 4px" }}>{b.status}</td>
                <td style={{ padding: "8px 4px" }}>₦{Number(b.total_amount).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
