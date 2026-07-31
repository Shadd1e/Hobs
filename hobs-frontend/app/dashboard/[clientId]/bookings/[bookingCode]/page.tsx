"use client";

/** GET /hotel/bookings/{booking_code}?client_id=... */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ApiError, getBooking, type BookingAdmin } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function BookingDetailPage() {
  const { session } = useAuth();
  const params = useParams<{ clientId: string; bookingCode: string }>();

  const [booking, setBooking] = useState<BookingAdmin | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!session) return;
    getBooking(session.access_token, params.bookingCode, params.clientId)
      .then(setBooking)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load booking."));
  }, [session, params.bookingCode, params.clientId]);

  return (
    <div>
      <Link href={`/dashboard/${params.clientId}/bookings`} className="helper-link">
        &larr; Back to bookings
      </Link>

      {error && <div className="banner-error" style={{ marginTop: 16 }}>{error}</div>}
      {!error && !booking && <p>Loading&hellip;</p>}

      {booking && (
        <div style={{ marginTop: 16 }}>
          <h1>{booking.booking_code}</h1>
          <Row label="Status" value={booking.status} />
          <Row label="Guest" value={booking.guest_name ?? "—"} />
          <Row label="Phone" value={booking.guest_phone ?? "—"} />
          <Row label="Dates" value={`${booking.check_in} → ${booking.check_out}`} />
          <Row label="Total" value={`₦${Number(booking.total_amount).toLocaleString()}`} />
          <Row
            label="Paid"
            value={booking.amount_paid != null ? `₦${Number(booking.amount_paid).toLocaleString()}` : "—"}
          />
          <Row label="Source" value={booking.source} />
          <Row label="Logged by staff" value={booking.logged_by_staff_phone ?? "—"} />
          <Row label="Payment ref" value={booking.payment_ref ?? "—"} />
          <Row label="Created" value={new Date(booking.created_at).toLocaleString()} />
          {booking.confirmed_at && <Row label="Confirmed" value={new Date(booking.confirmed_at).toLocaleString()} />}
          {booking.checked_in_at && <Row label="Checked in" value={new Date(booking.checked_in_at).toLocaleString()} />}
          {booking.checked_out_at && <Row label="Checked out" value={new Date(booking.checked_out_at).toLocaleString()} />}
          {booking.cancelled_at && <Row label="Cancelled" value={new Date(booking.cancelled_at).toLocaleString()} />}
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
