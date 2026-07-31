"use client";

/**
 * Bookings — GET /hotel/bookings?client_id=...&status=... (list, filterable)
 * and GET /hotel/bookings/{booking_code} (single lookup). Both admin-level
 * detail (RoomBookingAdminRead), merchant bearer token.
 * hotel_dashboard.py:277-314.
 */

import { Suspense, useEffect, useState, type FormEvent } from "react";
import { ApiError, getBooking, listBookings, type RoomBookingAdminRead } from "@/lib/api";
import { DashboardChrome } from "@/components/DashboardChrome";
import { useDashboardClient } from "@/components/useDashboardClient";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "CREATED", label: "Created" },
  { value: "PENDING_PAYMENT", label: "Pending payment" },
  { value: "PAID", label: "Paid" },
  { value: "CHECKED_IN", label: "Checked in" },
  { value: "CHECKED_OUT", label: "Checked out" },
  { value: "CANCELLED", label: "Cancelled" },
  { value: "REFUNDED", label: "Refunded" },
];

export default function BookingsPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <Bookings />
    </Suspense>
  );
}

function Bookings() {
  const {
    session,
    authLoading,
    clients,
    clientsError,
    loadingClients,
    clientId,
    selectClient,
  } = useDashboardClient();

  const [bookings, setBookings] = useState<RoomBookingAdminRead[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [status, setStatus] = useState("");

  const [lookupCode, setLookupCode] = useState("");
  const [lookupResult, setLookupResult] = useState<RoomBookingAdminRead | null>(null);
  const [lookupError, setLookupError] = useState<string | null>(null);
  const [lookupBusy, setLookupBusy] = useState(false);

  useEffect(() => {
    if (!session || !clientId) {
      setBookings(null);
      return;
    }
    let cancelled = false;
    setLoadingList(true);
    setListError(null);
    listBookings(session.access_token, clientId, status || undefined)
      .then((result) => {
        if (!cancelled) setBookings(result);
      })
      .catch((err) => {
        if (!cancelled) setListError(err instanceof ApiError ? err.message : "Couldn't load bookings.");
      })
      .finally(() => {
        if (!cancelled) setLoadingList(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session, clientId, status]);

  async function handleLookup(e: FormEvent) {
    e.preventDefault();
    if (!session || !clientId || !lookupCode.trim()) return;
    setLookupBusy(true);
    setLookupError(null);
    setLookupResult(null);
    try {
      const result = await getBooking(session.access_token, clientId, lookupCode.trim());
      setLookupResult(result);
    } catch (err) {
      setLookupError(err instanceof ApiError ? err.message : "Booking not found.");
    } finally {
      setLookupBusy(false);
    }
  }

  if (authLoading || !session || !session.email_verified) {
    return <main className="page">Loading&hellip;</main>;
  }

  return (
    <DashboardChrome
      merchantName={session.name}
      clients={clients}
      loadingClients={loadingClients}
      clientsError={clientsError}
      clientId={clientId}
      selectClient={selectClient}
    >
      <h1>Bookings</h1>
      <p className="subtitle">All bookings for this hotel, or look one up by its code.</p>

      <form className="dash-panel dash-panel-inline" onSubmit={handleLookup}>
        <div className="field" style={{ marginBottom: 0, flex: 1 }}>
          <label htmlFor="lookup">Look up by booking code</label>
          <input
            id="lookup"
            placeholder="e.g. HB7F3K2"
            value={lookupCode}
            onChange={(e) => setLookupCode(e.target.value)}
          />
        </div>
        <button className="btn" type="submit" style={{ width: "auto" }} disabled={lookupBusy}>
          {lookupBusy ? "Looking up…" : "Look up"}
        </button>
      </form>
      {lookupError && <div className="banner-error">{lookupError}</div>}
      {lookupResult && <BookingCard booking={lookupResult} />}

      <div className="dash-content-header">
        <h2 style={{ margin: 0 }}>All bookings</h2>
        <select value={status} onChange={(e) => setStatus(e.target.value)} style={{ width: "auto" }}>
          {STATUS_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {loadingList && <p className="dash-hint">Loading&hellip;</p>}
      {listError && <div className="banner-error">{listError}</div>}
      {bookings && bookings.length === 0 && <p className="dash-hint">No bookings match this filter.</p>}

      {bookings && bookings.length > 0 && (
        <table className="dash-table">
          <thead>
            <tr>
              <th>Code</th>
              <th>Guest</th>
              <th>Dates</th>
              <th>Status</th>
              <th>Total</th>
            </tr>
          </thead>
          <tbody>
            {bookings.map((b) => (
              <tr key={b.id}>
                <td>{b.booking_code}</td>
                <td>{b.guest_name ?? "—"}</td>
                <td>
                  {b.check_in} &rarr; {b.check_out}
                </td>
                <td>
                  <span className={`status-pill status-${b.status.toLowerCase()}`}>{b.status}</span>
                </td>
                <td>&#8358;{Number(b.total_amount).toLocaleString()}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </DashboardChrome>
  );
}

function BookingCard({ booking }: { booking: RoomBookingAdminRead }) {
  return (
    <div className="dash-panel">
      <h3 style={{ marginTop: 0 }}>
        {booking.booking_code} &mdash;{" "}
        <span className={`status-pill status-${booking.status.toLowerCase()}`}>{booking.status}</span>
      </h3>
      <dl className="detail-list">
        <dt>Guest</dt>
        <dd>{booking.guest_name ?? "—"}</dd>
        <dt>Phone</dt>
        <dd>{booking.guest_phone ?? "—"}</dd>
        <dt>Dates</dt>
        <dd>
          {booking.check_in} &rarr; {booking.check_out}
        </dd>
        <dt>Total / paid</dt>
        <dd>
          &#8358;{Number(booking.total_amount).toLocaleString()} /{" "}
          {booking.amount_paid != null ? `₦${Number(booking.amount_paid).toLocaleString()}` : "—"}
        </dd>
        <dt>Source</dt>
        <dd>{booking.source}</dd>
        <dt>Logged by</dt>
        <dd>{booking.logged_by_staff_phone ?? "—"}</dd>
        <dt>Payment ref</dt>
        <dd>{booking.payment_ref ?? "—"}</dd>
        <dt>Created</dt>
        <dd>{new Date(booking.created_at).toLocaleString()}</dd>
      </dl>
    </div>
  );
}
