"use client";

/** Wired to POST/GET/PATCH/DELETE /hotel/rooms. Needs room types loaded for the picker. */

import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "next/navigation";
import {
  ApiError,
  createRoom,
  deleteRoom,
  listRoomTypes,
  listRooms,
  updateRoom,
  type Room,
  type RoomType,
} from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RoomsManagePage() {
  const { session } = useAuth();
  const params = useParams<{ clientId: string }>();
  const clientId = params.clientId;

  const [rooms, setRooms] = useState<Room[] | null>(null);
  const [roomTypes, setRoomTypes] = useState<RoomType[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  function load() {
    if (!session) return;
    setError(null);
    Promise.all([listRooms(session.access_token, clientId), listRoomTypes(session.access_token, clientId)])
      .then(([r, rt]) => {
        setRooms(r);
        setRoomTypes(rt);
      })
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load rooms."));
  }

  useEffect(load, [session, clientId]);

  async function handleDelete(id: string) {
    if (!session) return;
    if (!confirm("Delete this room?")) return;
    try {
      await deleteRoom(session.access_token, id, clientId);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete.");
    }
  }

  if (!session) return null;

  if (roomTypes && roomTypes.length === 0) {
    return (
      <div>
        <h1>Manage rooms</h1>
        <p className="banner-info">
          Add at least one room type first, on the &ldquo;Room types&rdquo; tab —
          every room needs one.
        </p>
      </div>
    );
  }

  return (
    <div>
      {error && <div className="banner-error">{error}</div>}
      <h1>Manage rooms</h1>

      {roomTypes && (
        <CreateForm
          merchantId={session.merchant_id}
          clientId={clientId}
          token={session.access_token}
          roomTypes={roomTypes}
          onCreated={load}
        />
      )}

      {rooms === null ? (
        <p>Loading&hellip;</p>
      ) : rooms.length === 0 ? (
        <p className="subtitle">No rooms yet — add one above.</p>
      ) : (
        <div style={{ marginTop: 24 }}>
          {rooms.map((room) =>
            editingId === room.id ? (
              <EditForm
                key={room.id}
                room={room}
                clientId={clientId}
                token={session.access_token}
                roomTypes={roomTypes ?? []}
                onDone={() => {
                  setEditingId(null);
                  load();
                }}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <div
                key={room.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "12px 0",
                  borderBottom: "1px solid var(--line)",
                }}
              >
                <div>
                  <strong>{room.room_number}</strong>
                  <div style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                    {roomTypes?.find((rt) => rt.id === room.room_type_id)?.name ?? "Unknown type"}
                    {!room.is_active && " — inactive"}
                  </div>
                </div>
                <div className="btn-row" style={{ width: "auto" }}>
                  <button className="btn btn-secondary" style={{ width: "auto" }} onClick={() => setEditingId(room.id)}>
                    Edit
                  </button>
                  <button className="btn btn-secondary" style={{ width: "auto" }} onClick={() => handleDelete(room.id)}>
                    Delete
                  </button>
                </div>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}

function CreateForm({
  merchantId,
  clientId,
  token,
  roomTypes,
  onCreated,
}: {
  merchantId: string;
  clientId: string;
  token: string;
  roomTypes: RoomType[];
  onCreated: () => void;
}) {
  const [roomNumber, setRoomNumber] = useState("");
  const [roomTypeId, setRoomTypeId] = useState(roomTypes[0]?.id ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await createRoom(token, {
        room_number: roomNumber,
        room_type_id: roomTypeId,
        merchant_id: merchantId,
        client_id: clientId,
      });
      setRoomNumber("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create room.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
      {error && <div className="banner-error" style={{ width: "100%" }}>{error}</div>}
      <div className="field" style={{ marginBottom: 0, flex: "1 1 120px" }}>
        <label>Room number</label>
        <input required value={roomNumber} onChange={(e) => setRoomNumber(e.target.value)} placeholder="12B" />
      </div>
      <div className="field" style={{ marginBottom: 0, flex: "1 1 180px" }}>
        <label>Room type</label>
        <select value={roomTypeId} onChange={(e) => setRoomTypeId(e.target.value)}>
          {roomTypes.map((rt) => (
            <option key={rt.id} value={rt.id}>
              {rt.name}
            </option>
          ))}
        </select>
      </div>
      <button className="btn" type="submit" disabled={busy} style={{ width: "auto" }}>
        {busy ? "Adding…" : "Add"}
      </button>
    </form>
  );
}

function EditForm({
  room,
  clientId,
  token,
  roomTypes,
  onDone,
  onCancel,
}: {
  room: Room;
  clientId: string;
  token: string;
  roomTypes: RoomType[];
  onDone: () => void;
  onCancel: () => void;
}) {
  const [roomNumber, setRoomNumber] = useState(room.room_number);
  const [roomTypeId, setRoomTypeId] = useState(room.room_type_id);
  const [isActive, setIsActive] = useState(room.is_active);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await updateRoom(token, room.id, clientId, {
        room_number: roomNumber,
        room_type_id: roomTypeId,
        is_active: isActive,
      });
      onDone();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save changes.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end", padding: "12px 0", borderBottom: "1px solid var(--line)" }}
    >
      {error && <div className="banner-error" style={{ width: "100%" }}>{error}</div>}
      <div className="field" style={{ marginBottom: 0, flex: "1 1 120px" }}>
        <label>Room number</label>
        <input required value={roomNumber} onChange={(e) => setRoomNumber(e.target.value)} />
      </div>
      <div className="field" style={{ marginBottom: 0, flex: "1 1 180px" }}>
        <label>Room type</label>
        <select value={roomTypeId} onChange={(e) => setRoomTypeId(e.target.value)}>
          {roomTypes.map((rt) => (
            <option key={rt.id} value={rt.id}>
              {rt.name}
            </option>
          ))}
        </select>
      </div>
      <div className="checkbox-row" style={{ marginBottom: 0 }}>
        <input id={`active-${room.id}`} type="checkbox" checked={isActive} onChange={(e) => setIsActive(e.target.checked)} />
        <label htmlFor={`active-${room.id}`}>Active</label>
      </div>
      <button className="btn" type="submit" disabled={busy} style={{ width: "auto" }}>
        {busy ? "Saving…" : "Save"}
      </button>
      <button className="btn btn-secondary" type="button" onClick={onCancel} style={{ width: "auto" }}>
        Cancel
      </button>
    </form>
  );
}
