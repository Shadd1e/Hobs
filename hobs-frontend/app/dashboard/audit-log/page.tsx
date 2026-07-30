"use client";

/**
 * Staff audit log — app/api/v1/hotel_dashboard.py:316-402.
 * Uses the STAFF bearer token (lib/staffAuth.tsx), not the merchant token
 * — get_current_staff decodes a type:"staff" JWT and the route 403s if
 * staff.client_id doesn't match the selected hotel. Also hosts the
 * top_manager-only role-change flow (initiate sends an email code,
 * confirm applies it) since both live under the same staff-auth gate.
 */

import { Suspense, useEffect, useState, type FormEvent } from "react";
import Link from "next/link";
import {
  ApiError,
  confirmRoleChange,
  initiateRoleChange,
  listAuditLog,
  revertAuditLogEntry,
  type AuditLogEntry,
} from "@/lib/api";
import { DashboardChrome } from "@/components/DashboardChrome";
import { useDashboardClient } from "@/components/useDashboardClient";
import { useStaffAuth } from "@/lib/staffAuth";

export default function AuditLogPage() {
  return (
    <Suspense fallback={<main className="page">Loading&hellip;</main>}>
      <AuditLog />
    </Suspense>
  );
}

function AuditLog() {
  const {
    session,
    authLoading,
    clients,
    clientsError,
    loadingClients,
    clientId,
    selectClient,
  } = useDashboardClient();
  const { staffSession, staffLogout } = useStaffAuth();

  const [entries, setEntries] = useState<AuditLogEntry[] | null>(null);
  const [listError, setListError] = useState<string | null>(null);
  const [loadingList, setLoadingList] = useState(false);
  const [pendingOnly, setPendingOnly] = useState(false);
  const [revertBusyId, setRevertBusyId] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);

  function loadLog() {
    if (!staffSession || !clientId) return;
    setLoadingList(true);
    setListError(null);
    listAuditLog(staffSession.access_token, clientId, pendingOnly)
      .then((result) => setEntries(result))
      .catch((err) => {
        setListError(err instanceof ApiError ? err.message : "Couldn't load the audit log.");
      })
      .finally(() => setLoadingList(false));
  }

  useEffect(() => {
    loadLog();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [staffSession, clientId, pendingOnly]);

  async function handleRevert(entry: AuditLogEntry) {
    if (!staffSession) return;
    if (!window.confirm(`Revert this ${entry.action} action?`)) return;
    setRevertBusyId(entry.id);
    setActionMessage(null);
    try {
      await revertAuditLogEntry(staffSession.access_token, entry.id);
      setActionMessage("Action reverted.");
      loadLog();
    } catch (err) {
      window.alert(err instanceof ApiError ? err.message : "Couldn't revert this action.");
    } finally {
      setRevertBusyId(null);
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
      <h1>Audit log</h1>
      <p className="subtitle">Staff-logged actions on this hotel, with review and revert.</p>

      {!staffSession ? (
        <div className="banner-info">
          This section needs a staff sign-in (separate from your hotel account login).{" "}
          <Link href="/dashboard/staff-login">Sign in as staff &rarr;</Link>
        </div>
      ) : (
        <>
          <div className="dash-content-header">
            <span className="dash-hint" style={{ margin: 0 }}>
              Signed in as {staffSession.name ?? staffSession.staff_id} ({staffSession.role})
              {"  "}
              <button className="btn-link" onClick={staffLogout}>
                Sign out of staff account
              </button>
            </span>
            <label className="checkbox-row" style={{ margin: 0 }}>
              <input
                type="checkbox"
                checked={pendingOnly}
                onChange={(e) => setPendingOnly(e.target.checked)}
              />
              Pending review only
            </label>
          </div>

          {actionMessage && <div className="banner-info">{actionMessage}</div>}
          {loadingList && <p className="dash-hint">Loading&hellip;</p>}
          {listError && <div className="banner-error">{listError}</div>}
          {entries && entries.length === 0 && <p className="dash-hint">Nothing to show here.</p>}

          {entries && entries.length > 0 && (
            <table className="dash-table">
              <thead>
                <tr>
                  <th>When</th>
                  <th>Action</th>
                  <th>Status change</th>
                  <th>By</th>
                  <th>Flags</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((entry) => (
                  <tr key={entry.id}>
                    <td>{new Date(entry.created_at).toLocaleString()}</td>
                    <td>{entry.action}</td>
                    <td>
                      {entry.previous_status ?? "—"} &rarr; {entry.new_status ?? "—"}
                    </td>
                    <td>{entry.staff_phone ?? "—"}</td>
                    <td>
                      {entry.is_high_impact && <span className="status-pill status-cancelled">High impact</span>}{" "}
                      {entry.reviewed && <span className="status-pill status-checked_out">Reviewed</span>}{" "}
                      {entry.reverted && <span className="status-pill status-pending">Reverted</span>}
                    </td>
                    <td>
                      {!entry.reverted && (
                        <button
                          className="btn-link btn-link-danger"
                          onClick={() => handleRevert(entry)}
                          disabled={revertBusyId === entry.id}
                        >
                          {revertBusyId === entry.id ? "Reverting…" : "Revert"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {staffSession.role === "top_manager" && <RoleChangePanel staffToken={staffSession.access_token} />}
        </>
      )}
    </DashboardChrome>
  );
}

function RoleChangePanel({ staffToken }: { staffToken: string }) {
  const [targetStaffId, setTargetStaffId] = useState("");
  const [newRole, setNewRole] = useState("manager");
  const [requestId, setRequestId] = useState<string | null>(null);
  const [sentTo, setSentTo] = useState<string | null>(null);
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function handleInitiate(e: FormEvent) {
    e.preventDefault();
    setError(null);
    setMessage(null);
    if (!targetStaffId.trim()) {
      setError("Enter the target staff member's ID.");
      return;
    }
    setBusy(true);
    try {
      const result = await initiateRoleChange(staffToken, targetStaffId.trim(), newRole);
      setRequestId(result.request_id);
      setSentTo(result.sent_to);
      setMessage(`Confirmation code sent to ${result.sent_to}.`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't start the role change.");
    } finally {
      setBusy(false);
    }
  }

  async function handleConfirm(e: FormEvent) {
    e.preventDefault();
    if (!requestId) return;
    setError(null);
    setBusy(true);
    try {
      const result = await confirmRoleChange(staffToken, requestId, code.trim());
      setMessage(`Role updated to ${result.new_role}.`);
      setRequestId(null);
      setCode("");
      setTargetStaffId("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't confirm the role change.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="dash-panel">
      <h2>Change a staff member&rsquo;s role</h2>
      <p className="dash-hint">
        Top-manager only, email-code confirmed, never issued over WhatsApp.
      </p>
      {error && <div className="banner-error">{error}</div>}
      {message && <div className="banner-info">{message}</div>}

      {!requestId ? (
        <form onSubmit={handleInitiate}>
          <div className="field">
            <label htmlFor="target">Staff ID</label>
            <input
              id="target"
              required
              value={targetStaffId}
              onChange={(e) => setTargetStaffId(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="role">New role</label>
            <select id="role" value={newRole} onChange={(e) => setNewRole(e.target.value)}>
              <option value="receptionist">Receptionist</option>
              <option value="manager">Manager</option>
              <option value="top_manager">Top manager</option>
            </select>
          </div>
          <button className="btn" type="submit" style={{ width: "auto" }} disabled={busy}>
            {busy ? "Sending…" : "Send confirmation code"}
          </button>
        </form>
      ) : (
        <form onSubmit={handleConfirm}>
          <div className="field">
            <label htmlFor="code">Confirmation code (sent to {sentTo})</label>
            <input
              id="code"
              required
              inputMode="numeric"
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </div>
          <div className="btn-row">
            <button className="btn" type="submit" style={{ width: "auto" }} disabled={busy}>
              {busy ? "Confirming…" : "Confirm role change"}
            </button>
            <button className="btn btn-secondary" type="button" style={{ width: "auto" }} onClick={() => setRequestId(null)}>
              Cancel
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
