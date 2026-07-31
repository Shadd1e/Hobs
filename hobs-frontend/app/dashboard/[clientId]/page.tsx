"use client";

/** GET /hotel/dashboard/rooms?client_id=... — the non-admin room grid. */

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { ApiError, dashboardRooms, type RoomStatusRow } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RoomGridPage() {
  const { session } = useAuth();
  const params = useParams<{ clientId: string }>();
  const clientId = params.clientId;

  const [rooms, setRooms] = useState<RoomStatusRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  function load() {
    if (!session) return;
    setError(null);
    dashboardRooms(session.access_token, clientId)
      .then(setRooms)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load rooms."));
  }

  useEffect(load, [session, clientId]);

  if (error) return <div className="banner-error">{error}</div>;
  if (!rooms) return <p>Loading rooms&hellip;</p>;

  if (rooms.length === 0) {
    return (
      <div>
        <p className="subtitle">No rooms yet.</p>
        <Link href={`/dashboard/${clientId}/rooms-manage`} className="btn" style={{ width: "auto" }}>
          Add your first room
        </Link>
      </div>
    );
  }

  return (
    <div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))",
          gap: 12,
        }}
      >
        {rooms.map((room) => {
          const card = (
            <div
              style={{
                border: "1px solid var(--line)",
                borderRadius: 8,
                padding: 14,
                background: room.is_booked_today ? "#fdecea" : "#eef9f0",
                opacity: room.is_active ? 1 : 0.5,
              }}
            >
              <div style={{ fontWeight: 700, fontSize: "1.1rem" }}>{room.room_number}</div>
              <div style={{ fontSize: "0.8rem", color: "var(--muted)" }}>
                {room.room_type_name ?? "No room type"}
              </div>
              <div style={{ fontSize: "0.85rem", marginTop: 6 }}>
                {room.is_booked_today ? "Booked today" : "Free today"}
              </div>
              {!room.is_active && (
                <div style={{ fontSize: "0.75rem", color: "var(--muted)" }}>Inactive</div>
              )}
            </div>
          );

          return room.is_booked_today ? (
            <Link key={room.id} href={`/dashboard/${clientId}/rooms/${room.id}`} style={{ textDecoration: "none", color: "inherit" }}>
              {card}
            </Link>
          ) : (
            <div key={room.id}>{card}</div>
          );
        })}
      </div>
      <p className="field-hint" style={{ marginTop: 16 }}>
        Click a booked room to see guest details.
      </p>
    </div>
  );
}
