"use client";

/** GET /hotel/dashboard/rooms/{room_id}?client_id=... — admin drill-down. */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ApiError, dashboardRoomDetail, type RoomAdminDetail } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RoomDetailPage() {
  const { session } = useAuth();
  const params = useParams<{ clientId: string; roomId: string }>();

  const [detail, setDetail] = useState<RoomAdminDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    dashboardRoomDetail(session.access_token, params.roomId, params.clientId)
      .then(setDetail)
      .catch((err) =>
        setError(
          err instanceof ApiError
            ? err.status === 403
              ? "You don't have permission to view guest details."
              : err.message
            : "Couldn't load this room."
        )
      );
  }, [session, params.roomId, params.clientId]);

  return (
    <div>
      <Link href={`/dashboard/${params.clientId}`} className="helper-link">
        &larr; Back to rooms
      </Link>

      {error && <div className="banner-error" style={{ marginTop: 16 }}>{error}</div>}
      {!error && !detail && <p>Loading&hellip;</p>}

      {detail && (
        <div style={{ marginTop: 16 }}>
          <h1>Room {detail.room_number}</h1>
          {!detail.booking ? (
            <p className="subtitle">This room is free today.</p>
          ) : (
            <div>
              <Row label="Guest" value={detail.booking.guest_name ?? "—"} />
              <Row label="Phone" value={detail.booking.guest_phone ?? "—"} />
              <Row
                label="Dates"
                value={`${detail.booking.check_in} → ${detail.booking.check_out} (${detail.booking.nights} nights)`}
              />
              <Row label="Total" value={`₦${Number(detail.booking.total_amount).toLocaleString()}`} />
              <Row
                label="Paid"
                value={
                  detail.booking.amount_paid != null
                    ? `₦${Number(detail.booking.amount_paid).toLocaleString()}`
                    : "—"
                }
              />
              <Row label="Source" value={detail.booking.source} />
              <Row label="Logged by staff" value={detail.booking.logged_by_staff_phone ?? "—"} />
              <Row
                label="Booking code"
                value={
                  <Link href={`/dashboard/${params.clientId}/bookings/${detail.booking.booking_code}`}>
                    {detail.booking.booking_code}
                  </Link>
                }
              />
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", padding: "8px 0", borderBottom: "1px solid var(--line)" }}>
      <span style={{ color: "var(--muted)" }}>{label}</span>
      <span>{value}</span>
    </div>
  );
}
