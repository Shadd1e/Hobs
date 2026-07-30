"use client";

/**
 * Individual numbered rooms CRUD — app/api/v1/hotel_dashboard.py:207-274.
 * Each room belongs to a room_type (fetched here for the picker). POST
 * 409s on a duplicate room_number for this hotel.
 */

import { Suspense, useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  createRoom,
  deleteRoom,
  listRoomTypes,
  listRooms,
  updateRoom,
  type RoomRead,
  type RoomTypeRead,
} from "@/lib/api";
import { DashboardChrome } from "@/components/DashboardChrome";
import { useDashboardClient } from "@/components/useDashboardClient";

const emptyForm = { room_number: "", room_type_id: "", is_active: true };

export default function ManageRoomsPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <ManageRooms />
    </Suspense>
  );
}

function ManageRooms() {
  const {
    session,
    authLoading,
    clients,
    clientsError,
    loadingClients,
    clientId,
    selectClient,
  } = useDashboardClient();

  const [rooms, setRooms] = useState<RoomRead[] | null>(null);
  const [types, setTypes] = useState<RoomTypeRead[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function loadAll() {
    if (!session || !clientId) return;
    setLoadingList(true);
    setListError(null);
    Promise.all([listRooms(session.access_token, clientId), listRoomTypes(session.access_token, clientId)])
      .then(([r, t]) => {
        setRooms(r);
        setTypes(t);
      })
      .catch((err) => setListError(err instanceof ApiError ? err.message : "Couldn't load rooms."))
      .finally(() => setLoadingList(false));
  }

  useEffect(() => {
    loadAll();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, clientId]);

  function typeName(id: string) {
    return types?.find((t) => t.id === id)?.name ?? "Unknown type";
  }

  function startEdit(room: RoomRead) {
    setEditingId(room.id);
    setForm({ room_number: room.room_number, room_type_id: room.room_type_id, is_active: room.is_active });
    setFormError(null);
  }

  function startCreate() {
    setEditingId("new");
    setForm({ ...emptyForm, room_type_id: types?.[0]?.id ?? "" });
    setFormError(null);
  }

  function cancelEdit() {
    setEditingId(null);
    setForm(emptyForm);
    setFormError(null);
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    if (!session || !clientId || !editingId) return;
    setFormError(null);

    if (!form.room_number.trim()) {
      setFormError("Room number is required.");
      return;
    }
    if (!form.room_type_id) {
      setFormError("Choose a room type first — add one under \u201cRoom types\u201d if the list is empty.");
      return;
    }

    setSaving(true);
    try {
      if (editingId === "new") {
        await createRoom(session.access_token, clientId, session.merchant_id, {
          room_number: form.room_number.trim(),
          room_type_id: form.room_type_id,
          is_active: form.is_active,
        });
      } else {
        await updateRoom(session.access_token, clientId, editingId, {
          room_number: form.room_number.trim(),
          room_type_id: form.room_type_id,
          is_active: form.is_active,
        });
      }
      cancelEdit();
      loadAll();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(room: RoomRead) {
    if (!session || !clientId) return;
    if (!window.confirm(`Delete room ${room.room_number}? This can't be undone.`)) return;
    try {
      await deleteRoom(session.access_token, clientId, room.id);
      loadAll();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "Couldn't delete this room.");
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
      <div className="dash-content-header">
        <div>
          <h1>Manage rooms</h1>
          <p className="subtitle">Individual numbered rooms and which room type each belongs to.</p>
        </div>
        {editingId === null && (
          <button className="btn" style={{ width: "auto" }} onClick={startCreate}>
            + Add room
          </button>
        )}
      </div>

      {loadingList && <p className="dash-hint">Loading&hellip;</p>}
      {listError && <div className="banner-error">{listError}</div>}

      {types && types.length === 0 && (
        <p className="dash-hint">
          No room types yet — create one under &ldquo;Room types&rdquo; before adding rooms.
        </p>
      )}

      {editingId && (
        <form className="dash-panel" onSubmit={handleSubmit}>
          <h2>{editingId === "new" ? "New room" : "Edit room"}</h2>
          {formError && <div className="banner-error">{formError}</div>}

          <div className="field">
            <label htmlFor="room_number">Room number</label>
            <input
              id="room_number"
              required
              value={form.room_number}
              onChange={(e) => setForm({ ...form, room_number: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="room_type_id">Room type</label>
            <select
              id="room_type_id"
              required
              value={form.room_type_id}
              onChange={(e) => setForm({ ...form, room_type_id: e.target.value })}
            >
              <option value="" disabled>
                Select a room type&hellip;
              </option>
              {types?.map((t) => (
                <option key={t.id} value={t.id}>
                  {t.name}
                </option>
              ))}
            </select>
          </div>
          <div className="checkbox-row">
            <input
              id="is_active"
              type="checkbox"
              checked={form.is_active}
              onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
            />
            <label htmlFor="is_active">Active (available for booking)</label>
          </div>

          <div className="btn-row">
            <button className="btn" type="submit" disabled={saving}>
              {saving ? "Saving…" : "Save"}
            </button>
            <button className="btn btn-secondary" type="button" onClick={cancelEdit}>
              Cancel
            </button>
          </div>
        </form>
      )}

      {rooms && rooms.length === 0 && !editingId && <p className="dash-hint">No rooms yet.</p>}

      {rooms && rooms.length > 0 && (
        <table className="dash-table">
          <thead>
            <tr>
              <th>Room</th>
              <th>Type</th>
              <th>Status</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {rooms.map((r) => (
              <tr key={r.id}>
                <td>{r.room_number}</td>
                <td>{typeName(r.room_type_id)}</td>
                <td>{r.is_active ? "Active" : "Inactive"}</td>
                <td className="dash-table-actions">
                  <button className="btn-link" onClick={() => startEdit(r)}>
                    Edit
                  </button>
                  <button className="btn-link btn-link-danger" onClick={() => handleDelete(r)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </DashboardChrome>
  );
}
