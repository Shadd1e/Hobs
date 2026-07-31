"use client";

/**
 * Wired to POST/GET/PATCH/DELETE /hotel/room-types.
 * merchant_id comes from the logged-in session; client_id from the route.
 */

import { useEffect, useState, type FormEvent } from "react";
import { useParams } from "next/navigation";
import { ApiError, createRoomType, deleteRoomType, listRoomTypes, updateRoomType, type RoomType } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function RoomTypesPage() {
  const { session } = useAuth();
  const params = useParams<{ clientId: string }>();
  const clientId = params.clientId;

  const [roomTypes, setRoomTypes] = useState<RoomType[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);

  function load() {
    if (!session) return;
    setError(null);
    listRoomTypes(session.access_token, clientId)
      .then(setRoomTypes)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load room types."));
  }

  useEffect(load, [session, clientId]);

  async function handleDelete(id: string) {
    if (!session) return;
    if (!confirm("Delete this room type? This fails if any rooms still use it.")) return;
    try {
      await deleteRoomType(session.access_token, id, clientId);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't delete.");
    }
  }

  if (!session) return null;

  return (
    <div>
      {error && <div className="banner-error">{error}</div>}

      <h1>Room types</h1>
      <CreateForm
        merchantId={session.merchant_id}
        clientId={clientId}
        token={session.access_token}
        onCreated={load}
      />

      {roomTypes === null ? (
        <p>Loading&hellip;</p>
      ) : roomTypes.length === 0 ? (
        <p className="subtitle">No room types yet — add one above.</p>
      ) : (
        <div style={{ marginTop: 24 }}>
          {roomTypes.map((rt) =>
            editingId === rt.id ? (
              <EditForm
                key={rt.id}
                roomType={rt}
                clientId={clientId}
                token={session.access_token}
                onDone={() => {
                  setEditingId(null);
                  load();
                }}
                onCancel={() => setEditingId(null)}
              />
            ) : (
              <div
                key={rt.id}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "12px 0",
                  borderBottom: "1px solid var(--line)",
                }}
              >
                <div>
                  <strong>{rt.name}</strong>
                  <div style={{ fontSize: "0.85rem", color: "var(--muted)" }}>
                    ₦{rt.price.toLocaleString()} / night{rt.description ? ` — ${rt.description}` : ""}
                  </div>
                </div>
                <div className="btn-row" style={{ width: "auto" }}>
                  <button
                    className="btn btn-secondary"
                    style={{ width: "auto" }}
                    onClick={() => setEditingId(rt.id)}
                  >
                    Edit
                  </button>
                  <button
                    className="btn btn-secondary"
                    style={{ width: "auto" }}
                    onClick={() => handleDelete(rt.id)}
                  >
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
  onCreated,
}: {
  merchantId: string;
  clientId: string;
  token: string;
  onCreated: () => void;
}) {
  const [name, setName] = useState("");
  const [price, setPrice] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await createRoomType(token, {
        name,
        price: Number(price),
        description: description || null,
        merchant_id: merchantId,
        client_id: clientId,
      });
      setName("");
      setPrice("");
      setDescription("");
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create room type.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
      {error && <div className="banner-error" style={{ width: "100%" }}>{error}</div>}
      <div className="field" style={{ marginBottom: 0, flex: "1 1 160px" }}>
        <label>Name</label>
        <input required value={name} onChange={(e) => setName(e.target.value)} placeholder="Deluxe Room" />
      </div>
      <div className="field" style={{ marginBottom: 0, flex: "1 1 120px" }}>
        <label>Price / night (₦)</label>
        <input required type="number" min={1} value={price} onChange={(e) => setPrice(e.target.value)} />
      </div>
      <div className="field" style={{ marginBottom: 0, flex: "2 1 220px" }}>
        <label>Description (optional)</label>
        <input value={description} onChange={(e) => setDescription(e.target.value)} />
      </div>
      <button className="btn" type="submit" disabled={busy} style={{ width: "auto" }}>
        {busy ? "Adding…" : "Add"}
      </button>
    </form>
  );
}

function EditForm({
  roomType,
  clientId,
  token,
  onDone,
  onCancel,
}: {
  roomType: RoomType;
  clientId: string;
  token: string;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState(roomType.name);
  const [price, setPrice] = useState(String(roomType.price));
  const [description, setDescription] = useState(roomType.description ?? "");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      await updateRoomType(token, roomType.id, clientId, {
        name,
        price: Number(price),
        description: description || null,
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
      <div className="field" style={{ marginBottom: 0, flex: "1 1 160px" }}>
        <label>Name</label>
        <input required value={name} onChange={(e) => setName(e.target.value)} />
      </div>
      <div className="field" style={{ marginBottom: 0, flex: "1 1 120px" }}>
        <label>Price / night (₦)</label>
        <input required type="number" min={1} value={price} onChange={(e) => setPrice(e.target.value)} />
      </div>
      <div className="field" style={{ marginBottom: 0, flex: "2 1 220px" }}>
        <label>Description</label>
        <input value={description} onChange={(e) => setDescription(e.target.value)} />
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
