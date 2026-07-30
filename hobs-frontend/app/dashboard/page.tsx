"use client";

/**
 * Room grid — GET /hotel/dashboard/rooms?client_id=... (hotel_dashboard.py:100)
 * Click a room -> GET /hotel/dashboard/rooms/{room_id} for the admin
 * drill-down (guest name, dates, who logged it). Both use the merchant
 * bearer token, same as everything else in this file.
 */

import { Suspense, useEffect, useState } from "react";
import {
  ApiError,
  dashboardRoomDetail,
  dashboardRooms,
  type RoomAdminDetail,
  type RoomStatusRead,
} from "@/lib/api";
import { DashboardChrome } from "@/components/DashboardChrome";
import { useDashboardClient } from "@/components/useDashboardClient";

export default function DashboardPage() {
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

  const [rooms, setRooms] = useState<RoomStatusRead[] | null>(null);
  const [roomsError, setRoomsError] = useState<string | null>(null);
  const [loadingRooms, setLoadingRooms] = useState(false);

  const [detailRoomId, setDetailRoomId] = useState<string | null>(null);
  const [detail, setDetail] = useState<RoomAdminDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  useEffect(() => {
    if (!session || !clientId) {
      setRooms(null);
      return;
    }
    let cancelled = false;
    setLoadingRooms(true);
    setRoomsError(null);
    dashboardRooms(session.access_token, clientId)
      .then((result) => {
        if (!cancelled) setRooms(result);
      })
      .catch((err) => {
        if (!cancelled) setRoomsError(err instanceof ApiError ? err.message : "Couldn't load rooms.");
      })
      .finally(() => {
        if (!cancelled) setLoadingRooms(false);
      });
    return () => {
      cancelled = true;
    };
  }, [session, clientId]);

  function openDetail(roomId: string) {
    if (!session || !clientId) return;
    setDetailRoomId(roomId);
    setDetail(null);
    setDetailError(null);
    setLoadingDetail(true);
    dashboardRoomDetail(session.access_token, clientId, roomId)
      .then((result) => setDetail(result))
      .catch((err) => setDetailError(err instanceof ApiError ? err.message : "Couldn't load room detail."))
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
      <p className="subtitle">Today&rsquo;s status at a glance. Click a booked room for guest detail.</p>

      {loadingRooms && <p className="dash-hint">Loading rooms&hellip;</p>}
      {roomsError && <div className="banner-error">{roomsError}</div>}

      {rooms && rooms.length === 0 && (
        <p className="dash-hint">
          No rooms set up yet. Add room types and rooms from the &ldquo;Room types&rdquo; and
          &ldquo;Manage rooms&rdquo; tabs.
        </p>
      )}

      {rooms && rooms.length > 0 && (
        <div className="room-grid">
          {rooms.map((room) => (
            <button
              key={room.id}
              className={`room-card ${room.is_booked_today ? "booked" : "free"}${
                !room.is_active ? " inactive" : ""
              }`}
              onClick={() => openDetail(room.id)}
            >
              <span className="room-number">{room.room_number}</span>
              <span className="room-type">{room.room_type_name ?? "No type"}</span>
              <span className="room-status-pill">
                {!room.is_active ? "Inactive" : room.is_booked_today ? "Booked" : "Free"}
              </span>
            </button>
          ))}
        </div>
      )}

      {detailRoomId && (
        <div className="modal-backdrop" onClick={() => setDetailRoomId(null)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setDetailRoomId(null)} aria-label="Close">
              &times;
            </button>
            {loadingDetail && <p className="dash-hint">Loading&hellip;</p>}
            {detailError && <div className="banner-error">{detailError}</div>}
            {detail && (
              <>
                <h2>Room {detail.room_number}</h2>
                {detail.booking ? (
                  <dl className="detail-list">
                    <dt>Guest</dt>
                    <dd>{detail.booking.guest_name ?? "—"}</dd>
                    <dt>Phone</dt>
                    <dd>{detail.booking.guest_phone ?? "—"}</dd>
                    <dt>Check-in</dt>
                    <dd>{detail.booking.check_in}</dd>
                    <dt>Check-out</dt>
                    <dd>{detail.booking.check_out}</dd>
                    <dt>Nights</dt>
                    <dd>{detail.booking.nights}</dd>
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
                    <dt>Logged by</dt>
                    <dd>{detail.booking.logged_by_staff_phone ?? "—"}</dd>
                    <dt>Booking code</dt>
                    <dd>{detail.booking.booking_code}</dd>
                  </dl>
                ) : (
                  <p className="dash-hint">This room is free today.</p>
                )}
              </>
            )}
          </div>
        </div>
      )}
    </DashboardChrome>
  );
}
