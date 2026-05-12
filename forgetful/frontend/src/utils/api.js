// utils/api.js — thin wrappers around the FastAPI backend

const BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

async function request(method, path, body) {
  const res = await fetch(`${BASE}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Persons ──────────────────────────────────────────────────
export const registerPerson = (
  image_b64,
  role = "person",
  name = null,
  person_id = null
) =>
  request("POST", "/api/persons/register", {
    image_b64,
    role,
    name,
    ...(person_id ? { person_id } : {}),
  });

export const listPersons = () => request("GET", "/api/persons/");

export const updatePersonName = (id, name) =>
  request("PATCH", `/api/persons/${id}/name`, { name });

/** Wipes persons + interactions (requires ALLOW_FULL_DATABASE_RESET=true on backend). */
export const resetAllDemoData = () =>
  request("POST", "/api/admin/reset-all", { confirm: "DELETE_ALL_DATA" });

// ── Recognition ──────────────────────────────────────────────
export const identifyFace = (image_b64) =>
  request("POST", "/api/recognition/identify", { image_b64 });

// ── Interactions ─────────────────────────────────────────────
export const getLatestInteraction = (person_id, opts = {}) => {
  const solo = opts.patientSoloOnly ? "?patient_solo_only=true" : "";
  return request("GET", `/api/interactions/${person_id}/latest${solo}`);
};

export const listInteractions = (person_id, limit = 20) =>
  request("GET", `/api/interactions/${person_id}?limit=${limit}`);

export const createInteraction = (
  person_id,
  transcript,
  image_b64 = null,
  patient_solo = undefined
) =>
  request("POST", "/api/interactions/", {
    person_id,
    transcript,
    image_b64,
    ...(patient_solo === true ? { patient_solo: true } : {}),
  });
