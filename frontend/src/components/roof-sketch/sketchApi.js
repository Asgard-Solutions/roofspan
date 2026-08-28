// Office sketch API adapter. Encapsulates get/list/save + conflict(409)/validation(422) parsing.
import { api } from "@/lib/api";

const base = (revisionId) => `/measurements/${revisionId}/sketches`;

export async function listSketches(revisionId) {
  const { data } = await api.get(base(revisionId));
  return data;
}

// Returns the sketch record, or null when none exists yet (404).
export async function getSketch(revisionId, structureId) {
  try {
    const { data } = await api.get(`${base(revisionId)}/${structureId}`);
    return data;
  } catch (e) {
    if (e?.response?.status === 404) return null;
    throw e;
  }
}

// PUT the canonical envelope. Resolves { ok:true, record } on success, or a structured failure:
//   { ok:false, kind:"conflict", server }        (HTTP 409 — stale version, server doc preserved)
//   { ok:false, kind:"validation", message }     (HTTP 422 — invalid canonical document)
//   { ok:false, kind:"forbidden"|"locked"|"error", message }
export async function saveSketch(revisionId, structureId, { document, editMode, schemaVersion = 1, expectedVersion }) {
  try {
    const { data } = await api.put(`${base(revisionId)}/${structureId}`, {
      schema_version: schemaVersion,
      edit_mode: editMode,
      document,
      expected_version: expectedVersion ?? null,
    });
    return { ok: true, record: data };
  } catch (e) {
    const status = e?.response?.status;
    const detail = e?.response?.data?.detail;
    if (status === 409) {
      const server = detail && typeof detail === "object" ? detail.server || detail : null;
      return { ok: false, kind: "conflict", server, message: "This roof sketch was changed after you opened it." };
    }
    if (status === 422) {
      const msg = typeof detail === "string" ? detail
        : Array.isArray(detail) ? detail.map((d) => d?.msg || JSON.stringify(d)).join("; ")
        : detail?.message || detail?.msg || "The sketch could not be validated by the server.";
      return { ok: false, kind: "validation", message: msg };
    }
    if (status === 409) return { ok: false, kind: "conflict", server: null, message: "Conflict." };
    const locked = typeof detail === "string" && detail.toLowerCase().includes("locked");
    if (locked) return { ok: false, kind: "locked", message: detail };
    if (status === 403) return { ok: false, kind: "forbidden", message: "You are not authorized for this record." };
    return { ok: false, kind: "error", message: (typeof detail === "string" && detail) || e?.message || "Save failed." };
  }
}
