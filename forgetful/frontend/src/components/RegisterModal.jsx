// components/RegisterModal.jsx
// Captures a webcam screenshot and registers the face with the backend.

import React, { useRef, useState, useEffect, useMemo } from "react";
import Webcam from "react-webcam";
import { registerPerson } from "../utils/api";

/**
 * @param {Array<{ person_id: string, name: string }>} updateTargets
 *        Known visitors currently on camera — choose one to rename / refresh face (same DB row).
 */
export default function RegisterModal({
  onClose,
  onRegistered,
  requiredRole = null,
  updateTargets = [],
}) {
  const webcamRef = useRef(null);
  const [role, setRole] = useState(requiredRole || "person");
  const [name, setName] = useState("");
  /** null = brand-new visitor row; uuid = update that person */
  const [updatePersonId, setUpdatePersonId] = useState(null);
  const [preview, setPreview] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const lockRole = Boolean(requiredRole);

  const visitorSig = useMemo(
    () => updateTargets.map((t) => t.person_id).sort().join(","),
    [updateTargets]
  );
  const targetsRef = useRef(updateTargets);
  targetsRef.current = updateTargets;

  // Default to “update this visitor” when exactly one is visible (deps use stable sig only)
  useEffect(() => {
    if (lockRole) return;
    if (!visitorSig || visitorSig.includes(",")) return;
    const t0 = targetsRef.current.find((t) => t.person_id === visitorSig);
    if (!t0) return;
    setUpdatePersonId((cur) => (cur == null ? t0.person_id : cur));
    setName((prev) => prev || t0.name || "");
  }, [lockRole, visitorSig]);

  const capture = () => {
    const shot = webcamRef.current?.getScreenshot();
    if (shot) setPreview(shot);
  };

  const submit = async () => {
    if (!preview) return;
    setLoading(true);
    setError(null);
    try {
      const b64 = preview.replace(/^data:image\/\w+;base64,/, "");
      const pid = updatePersonId || null;
      const submitRole = lockRole ? role : "person";
      const result = await registerPerson(b64, submitRole, name || null, pid);
      onRegistered(result.person);
      onClose();
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div style={{
      position: "fixed", inset: 0, background: "#000000bb", display: "flex",
      alignItems: "center", justifyContent: "center", zIndex: 100,
    }}>
      <div className="card fade-in" style={{ width: 420, maxWidth: "94vw" }}>
        <h2 style={{ fontFamily: "var(--font-head)", marginBottom: "0.35rem" }}>
          {lockRole ? "Register Patient" : "Register visitor"}
        </h2>
        {!lockRole && (
          <p style={{ fontSize: "0.76rem", color: "var(--muted)", marginBottom: "0.85rem", lineHeight: 1.4 }}>
            Patient is only registered once at startup. Here you add visitors or{" "}
            <strong style={{ color: "var(--text)" }}>save a real name</strong> for someone already shown as Visitor 1, 2, …
          </p>
        )}

        {!lockRole && updateTargets.length > 0 && (
          <div style={{ marginBottom: "0.75rem" }}>
            <label style={{ display: "block", fontSize: "0.78rem", color: "var(--muted)", marginBottom: "0.35rem" }}>
              Save detected visitor as…
            </label>
            <select
              value={updatePersonId ?? ""}
              onChange={(e) => {
                const v = e.target.value;
                setUpdatePersonId(v || null);
                if (v) {
                  const t = updateTargets.find((x) => x.person_id === v);
                  if (t) setName(t.name || "");
                }
              }}
              style={{ width: "100%" }}
            >
              <option value="">New visitor (new profile)</option>
              {updateTargets.map((t) => (
                <option key={t.person_id} value={t.person_id}>
                  “{t.name || "Visitor"}” — save with a new name (same person)
                </option>
              ))}
            </select>
            <p style={{ fontSize: "0.72rem", color: "var(--muted)", margin: "0.35rem 0 0" }}>
              Type the name below, <strong>Capture</strong>, then <strong>Save name &amp; face</strong> — Visitor 1 becomes that name.
            </p>
          </div>
        )}

        {!lockRole && updateTargets.length === 0 && (
          <p style={{ fontSize: "0.72rem", color: "var(--muted)", marginBottom: "0.75rem", lineHeight: 1.4 }}>
            No visitor label on camera yet. Stand in frame until you see <strong>Visitor 1</strong>, then open{" "}
            <strong>Register Face</strong> again — or stay here to register a brand-new visitor.
          </p>
        )}

        <div style={{ marginBottom: "0.75rem", display: "flex", gap: "0.5rem" }}>
          <input
            placeholder={
              updatePersonId
                ? "Name to show (e.g. Ali)"
                : lockRole
                  ? "Patient name (optional)"
                  : "Visitor name (optional)"
            }
            value={name}
            onChange={(e) => setName(e.target.value)}
            style={{ flex: 1 }}
          />
          {lockRole ? (
            <div style={{ minWidth: 110, display: "grid", placeItems: "center", borderRadius: 8, border: "1px solid var(--border)", color: "var(--muted)" }}>
              Patient
            </div>
          ) : (
            <div style={{ minWidth: 110, display: "grid", placeItems: "center", borderRadius: 8, border: "1px solid var(--border)", color: "var(--muted)", fontSize: "0.85rem" }}>
              Visitor
            </div>
          )}
        </div>

        <div style={{ borderRadius: 8, overflow: "hidden", marginBottom: "0.75rem", position: "relative" }}>
          {preview ? (
            <img src={preview} alt="Preview" style={{ width: "100%", display: "block" }} />
          ) : (
            <Webcam ref={webcamRef} screenshotFormat="image/jpeg" style={{ width: "100%", display: "block" }} />
          )}
        </div>

        {error && (
          <p style={{ color: "var(--danger)", fontSize: "0.8rem", marginBottom: "0.5rem" }}>{error}</p>
        )}

        <div style={{ display: "flex", gap: "0.5rem" }}>
          {preview ? (
            <>
              <button className="btn-secondary" onClick={() => setPreview(null)}>Retake</button>
              <button className="btn-primary" onClick={submit} disabled={loading} style={{ flex: 1 }}>
                {loading ? "Saving…" : updatePersonId ? "Save name & face" : "Register"}
              </button>
            </>
          ) : (
            <button className="btn-primary" onClick={capture} style={{ flex: 1 }}>
              {updatePersonId ? "Capture for name save" : "Capture"}
            </button>
          )}
          {!lockRole && <button className="btn-secondary" onClick={onClose}>Cancel</button>}
        </div>
      </div>
    </div>
  );
}
