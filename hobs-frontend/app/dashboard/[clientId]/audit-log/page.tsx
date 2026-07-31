"use client";

/**
 * GET /hotel/audit-log?client_id=&pending_only= and POST
 * /hotel/audit-log/{id}/revert — both require the STAFF token from
 * lib/staffAuth.tsx, not the merchant token. If no staff session exists,
 * this page sends the user to /staff-login rather than reusing the
 * merchant login — they're genuinely different credentials on the backend.
 */

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import {
  ApiError,
  confirmRoleChange,
  initiateRoleChange,
  listAuditLog,
  revertAuditLogEntry,
  type AuditLogEntry,
} from "@/lib/api";
import { useStaffAuth } from "@/lib/staffAuth";

export default function AuditLogPage() {
  const { staffSession, loading } = useStaffAuth();
  const router = useRouter();
  const params = useParams<{ clientId: string }>();
  const clientId = params.clientId;

  const [entries, setEntries] = useState<AuditLogEntry[] | null>(null);
  const [pendingOnly, setPendingOnly] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (loading) return;
    if (!staffSession) {
      router.push(`/staff-login?returnTo=/dashboard/${clientId}/audit-log`);
    }
  }, [loading, staffSession, router, clientId]);

  function load() {
    if (!staffSession) return;
    setError(null);
    listAuditLog(staffSession.access_token, clientId, pendingOnly)
      .then(setEntries)
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) {
          // Staff token expired/invalid — force a fresh staff login rather
          // than showing a dead list.
          router.push(`/staff-login?returnTo=/dashboard/${clientId}/audit-log`);
          return;
        }
        setError(err instanceof ApiError ? err.message : "Couldn't load the audit log.");
      });
  }

  useEffect(load, [staffSession, clientId, pendingOnly]);

  async function handleRevert(id: string) {
    if (!staffSession) return;
    if (!confirm("Revert this action? This can't be undone once the revert window closes.")) return;
    try {
      await revertAuditLogEntry(staffSession.access_token, id);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't revert.");
    }
  }

  if (loading || !staffSession) return <p>Checking staff session&hellip;</p>;

  return (
    <div>
      <h1>Staff audit log</h1>
      <p className="subtitle">Signed in as staff {staffSession.name ?? staffSession.staff_id} ({staffSession.role}).</p>

      <div className="checkbox-row">
        <input
          id="pending_only"
          type="checkbox"
          checked={pendingOnly}
          onChange={(e) => setPendingOnly(e.target.checked)}
        />
        <label htmlFor="pending_only">Pending review only</label>
      </div>

      {error && <div className="banner-error">{error}</div>}
      {!error && entries === null && <p>Loading&hellip;</p>}
      {entries && entries.length === 0 && <p className="subtitle">No entries.</p>}

      {entries && entries.length > 0 && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr style={{ textAlign: "left", borderBottom: "1px solid var(--line)" }}>
              <th style={{ padding: "8px 4px" }}>When</th>
              <th style={{ padding: "8px 4px" }}>Action</th>
              <th style={{ padding: "8px 4px" }}>Status change</th>
              <th style={{ padding: "8px 4px" }}>By</th>
              <th style={{ padding: "8px 4px" }}></th>
            </tr>
          </thead>
          <tbody>
            {entries.map((e) => (
              <tr key={e.id} style={{ borderBottom: "1px solid var(--line)" }}>
                <td style={{ padding: "8px 4px" }}>{new Date(e.created_at).toLocaleString()}</td>
                <td style={{ padding: "8px 4px" }}>
                  {e.action}
                  {e.is_high_impact && (
                    <span style={{ color: "var(--danger)", marginLeft: 6, fontSize: "0.75rem" }}>high impact</span>
                  )}
                </td>
                <td style={{ padding: "8px 4px" }}>
                  {e.previous_status ?? "—"} → {e.new_status ?? "—"}
                </td>
                <td style={{ padding: "8px 4px" }}>{e.staff_phone ?? "—"}</td>
                <td style={{ padding: "8px 4px" }}>
                  {e.reverted ? (
                    <span style={{ color: "var(--muted)" }}>Reverted</span>
                  ) : e.revert_expires_at && new Date(e.revert_expires_at) > new Date() ? (
                    <button
                      className="btn btn-secondary"
                      style={{ width: "auto", padding: "4px 10px", fontSize: "0.8rem" }}
                      onClick={() => handleRevert(e.id)}
                    >
                      Revert
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {staffSession.role === "top_manager" && (
        <RoleChangePanel token={staffSession.access_token} />
      )}
    </div>
  );
}

function RoleChangePanel({ token }: { token: string }) {
  const [targetStaffId, setTargetStaffId] = useState("");
  const [newRole, setNewRole] = useState<"receptionist" | "manager" | "top_manager">("receptionist");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleInitiate() {
    setError(null);
    setInfo(null);
    setBusy(true);
    try {
      const result = await initiateRoleChange(token, targetStaffId, newRole);
      setRequestId(result.request_id);
      setSentTo(result.sent_to);
      setInfo(`Confirmation code sent to ${result.sent_to}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start the role change.");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm() {
    if (!requestId) return;
    setError(null);
    setBusy(true);
    try {
      const result = await confirmRoleChange(token, requestId, code);
      setInfo(`Staff ${result.staff_id} is now ${result.new_role}.`);
      setRequestId(null);
      setSentTo(null);
      setCode("");
      setTargetStaffId("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't confirm the role change.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div style={{ marginTop: 32, paddingTop: 24, borderTop: "1px solid var(--line)" }}>
      <h2 style={{ fontSize: "1.1rem" }}>Change a staff member&rsquo;s role</h2>
      <p className="field-hint">
        Sends a confirmation code to your own registered email — never over WhatsApp — before applying.
      </p>

      {error && <div className="banner-error">{error}</div>}
      {info && <div className="banner-info">{info}</div>}

      {!requestId ? (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="field" style={{ marginBottom: 0, flex: "1 1 200px" }}>
            <label>Staff ID</label>
            <input value={targetStaffId} onChange={(e) => setTargetStaffId(e.target.value)} />
          </div>
          <div className="field" style={{ marginBottom: 0, flex: "1 1 160px" }}>
            <label>New role</label>
            <select value={newRole} onChange={(e) => setNewRole(e.target.value as typeof newRole)}>
              <option value="receptionist">Receptionist</option>
              <option value="manager">Manager</option>
              <option value="top_manager">Top manager</option>
            </select>
          </div>
          <button className="btn" style={{ width: "auto" }} onClick={handleInitiate} disabled={busy || !targetStaffId}>
            {busy ? "Sending…" : "Send confirmation code"}
          </button>
        </div>
      ) : (
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap", alignItems: "flex-end" }}>
          <div className="field" style={{ marginBottom: 0, flex: "1 1 160px" }}>
            <label>Code sent to {sentTo}</label>
            <input
              inputMode="numeric"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
            />
          </div>
          <button className="btn" style={{ width: "auto" }} onClick={handleConfirm} disabled={busy || code.length !== 6}>
            {busy ? "Confirming…" : "Confirm"}
          </button>
          <button className="btn btn-secondary" style={{ width: "auto" }} onClick={() => setRequestId(null)}>
            Cancel
          </button>
        </div>
      )}
    </div>
  );
}
