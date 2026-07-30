"use client";

/**
 * Room types CRUD — app/api/v1/hotel_dashboard.py:136-205.
 * POST 409s if the name is already used for this hotel; PATCH is partial
 * (used for price-only adjustments too); DELETE 409s if rooms still
 * reference the type.
 */

import { Suspense, useEffect, useState, type FormEvent } from "react";
import {
  ApiError,
  createRoomType,
  deleteRoomType,
  listRoomTypes,
  updateRoomType,
  type RoomTypeRead,
} from "@/lib/api";
import { DashboardChrome } from "@/components/DashboardChrome";
import { useDashboardClient } from "@/components/useDashboardClient";

const emptyForm = { name: "", description: "", price: "", image_url: "" };

export default function RoomTypesPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <RoomTypes />
    </Suspense>
  );
}

function RoomTypes() {
  const {
    session,
    authLoading,
    clients,
    clientsError,
    loadingClients,
    clientId,
    selectClient,
  } = useDashboardClient();

  const [types, setTypes] = useState<RoomTypeRead[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(false);

  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState(emptyForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  function loadTypes() {
    if (!session || !clientId) return;
    setLoadingList(true);
    setListError(null);
    listRoomTypes(session.access_token, clientId)
      .then((result) => setTypes(result))
      .catch((err) => setListError(err instanceof ApiError ? err.message : "Couldn't load room types."))
      .finally(() => setLoadingList(false));
  }

  useEffect(() => {
    loadTypes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, clientId]);

  function startEdit(type: RoomTypeRead) {
    setEditingId(type.id);
    setForm({
      name: type.name,
      description: type.description ?? "",
      price: String(type.price),
      image_url: type.image_url ?? "",
    });
    setFormError(null);
  }

  function startCreate() {
    setEditingId("new");
    setForm(emptyForm);
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

    const price = Number(form.price);
    if (!form.name.trim()) {
      setFormError("Name is required.");
      return;
    }
    if (!Number.isFinite(price) || price <= 0) {
      setFormError("Price must be a number greater than 0.");
      return;
    }

    setSaving(true);
    try {
      const input = {
        name: form.name.trim(),
        description: form.description.trim() || null,
        price,
        image_url: form.image_url.trim() || null,
      };
      if (editingId === "new") {
        await createRoomType(session.access_token, clientId, session.merchant_id, input);
      } else {
        await updateRoomType(session.access_token, clientId, editingId, input);
      }
      cancelEdit();
      loadTypes();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(type: RoomTypeRead) {
    if (!session || !clientId) return;
    if (!window.confirm(`Delete "${type.name}"? This can't be undone.`)) return;
    try {
      await deleteRoomType(session.access_token, clientId, type.id);
      loadTypes();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "Couldn't delete this room type.");
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
          <h1>Room types</h1>
          <p className="subtitle">Categories like &ldquo;Deluxe Room&rdquo; with a flat nightly rate.</p>
        </div>
        {editingId === null && (
          <button className="btn" style={{ width: "auto" }} onClick={startCreate}>
            + Add room type
          </button>
        )}
      </div>

      {loadingList && <p className="dash-hint">Loading&hellip;</p>}
      {listError && <div className="banner-error">{listError}</div>}

      {editingId && (
        <form className="dash-panel" onSubmit={handleSubmit}>
          <h2>{editingId === "new" ? "New room type" : "Edit room type"}</h2>
          {formError && <div className="banner-error">{formError}</div>}

          <div className="field">
            <label htmlFor="name">Name</label>
            <input
              id="name"
              required
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="description">Description</label>
            <textarea
              id="description"
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="price">Nightly rate (&#8358;)</label>
            <input
              id="price"
              type="number"
              min="0"
              step="0.01"
              required
              value={form.price}
              onChange={(e) => setForm({ ...form, price: e.target.value })}
            />
          </div>
          <div className="field">
            <label htmlFor="image_url">Image URL (optional)</label>
            <input
              id="image_url"
              type="url"
              value={form.image_url}
              onChange={(e) => setForm({ ...form, image_url: e.target.value })}
            />
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

      {types && types.length === 0 && !editingId && (
        <p className="dash-hint">No room types yet. Add one to start creating rooms.</p>
      )}

      {types && types.length > 0 && (
        <table className="dash-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Description</th>
              <th>Rate</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {types.map((t) => (
              <tr key={t.id}>
                <td>{t.name}</td>
                <td>{t.description ?? "—"}</td>
                <td>&#8358;{Number(t.price).toLocaleString()}</td>
                <td className="dash-table-actions">
                  <button className="btn-link" onClick={() => startEdit(t)}>
                    Edit
                  </button>
                  <button className="btn-link btn-link-danger" onClick={() => handleDelete(t)}>
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
