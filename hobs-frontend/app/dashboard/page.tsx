"use client";

/**
 * The "Rooms" tab (root of /dashboard) — today's free/booked status per
 * room, with a click-through admin detail for booked ones.
 * GET /hotel/dashboard/rooms?client_id=... (grid) and GET
 * /hotel/dashboard/rooms/{room_id}?client_id=... (drill-down),
 * hotel_dashboard.py:100-133.
 */

import { Suspense, useEffect, useState } from "react";
import {
  ApiError,
  dashboardRoomDetail,
  dashboardRooms,
  type RoomAdminDetail,
  type RoomStatusRow,
} from "@/lib/api";
import { DashboardChrome } from "@/components/DashboardChrome";
import { useDashboardClient } from "@/components/useDashboardClient";

export default function RoomGridPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <RoomGrid />
    </Suspense>
  );
}

function RoomGrid() {
  const {
    session,
    authLoading,
    clients,
    clientsError,
    loadingClients,
    clientId,
    selectClient,
  } = useDashboardClient();

  const [rooms, setRooms] = useState<RoomStatusRow[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loadingRooms, setLoadingRooms] = useState(false);

  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RoomAdminDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  function loadRooms() {
    if (!session || !clientId) {
      setRooms(null);
      return;
    }
    setLoadingRooms(true);
    setListError(null);
    dashboardRooms(session.access_token, clientId)
      .then(setRooms)
      .catch((err) => setListError(err instanceof ApiError ? err.message : "Couldn't load rooms."))
      .finally(() => setLoadingRooms(false));
  }

  useEffect(loadRooms, [session, clientId]);

  function openRoom(roomId: string) {
    if (!session || !clientId) return;
    setSelectedRoomId(roomId);
    setDetail(null);
    setDetailError(null);
    setLoadingDetail(true);
    dashboardRoomDetail(session.access_token, roomId, clientId)
      .then(setDetail)
      .catch((err) =>
        setDetailError(
          err instanceof ApiError
            ? err.status === 403
              ? "You don't have permission to view guest details."
              : err.message
            : "Couldn't load this room."
        )
      )
      .finally(() => setLoadingDetail(false));
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
      <h1>Rooms</h1>
      <p className="subtitle">Today&rsquo;s status for every room. Click a booked room for guest details.</p>

      {loadingRooms && <p className="dash-hint">Loading&hellip;</p>}
      {listError && <div className="banner-error">{listError}</div>}
      {rooms && rooms.length === 0 && <p className="dash-hint">No rooms yet — add some under &ldquo;Manage rooms&rdquo;.</p>}

      {rooms && rooms.length > 0 && (
        <div className="room-grid">
          {rooms.map((room) => (
            <button
              key={room.id}
              className={`room-card ${room.is_booked_today ? "room-card-booked" : "room-card-free"}${
                !room.is_active ? " room-card-inactive" : ""
              }`}
              onClick={() => room.is_booked_today && openRoom(room.id)}
              disabled={!room.is_booked_today}
            >
              <div className="room-card-number">{room.room_number}</div>
              <div className="room-card-type">{room.room_type_name ?? "No room type"}</div>
              <div className="room-card-status">{room.is_booked_today ? "Booked today" : "Free today"}</div>
              {!room.is_active && <div className="room-card-flag">Inactive</div>}
            </button>
          ))}
        </div>
      )}

      {selectedRoomId && (
        <div className="dash-panel" style={{ marginTop: 24 }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h2 style={{ margin: 0 }}>Room detail</h2>
            <button className="btn-link" onClick={() => setSelectedRoomId(null)}>
              Close
            </button>
          </div>

          {loadingDetail && <p className="dash-hint">Loading&hellip;</p>}
          {detailError && <div className="banner-error">{detailError}</div>}

          {detail && (
            <div>
              <h3>Room {detail.room_number}</h3>
              {!detail.booking ? (
                <p className="subtitle">This room is free today.</p>
              ) : (
                <dl className="detail-list">
                  <dt>Guest</dt>
                  <dd>{detail.booking.guest_name ?? "—"}</dd>
                  <dt>Phone</dt>
                  <dd>{detail.booking.guest_phone ?? "—"}</dd>
                  <dt>Dates</dt>
                  <dd>
                    {detail.booking.check_in} &rarr; {detail.booking.check_out} ({detail.booking.nights} nights)
                  </dd>
                  <dt>Total</dt>
                  <dd>&#8358;{Number(detail.booking.total_amount).toLocaleString()}</dd>
                  <dt>Paid</dt>
                  <dd>
                    {detail.booking.amount_paid != null
                      ? `₦${Number(detail.booking.amount_paid).toLocaleString()}`
                      : "—"}
                  </dd>
                  <dt>Source</dt>
                  <dd>{detail.booking.source}</dd>
                  <dt>Logged by staff</dt>
                  <dd>{detail.booking.logged_by_staff_phone ?? "—"}</dd>
                  <dt>Booking code</dt>
                  <dd>{detail.booking.booking_code}</dd>
                </dl>
              )}
            </div>
          )}
        </div>
      )}
    </DashboardChrome>
  );
}
