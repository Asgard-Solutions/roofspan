// Field-optimized: high contrast, large touch targets, minimal chrome.
export const C = {
  bg: "#0F172A",
  surface: "#FFFFFF",
  ink: "#0F172A",
  sub: "#475569",
  line: "#E2E8F0",
  brand: "#EA580C",
  ok: "#059669",
  warn: "#B45309",
  danger: "#DC2626",
  dnk: "#DC2626",
};

// Property pin colors — MUST match RoofSpan Office map legend exactly.
export const PIN = {
  owned: "#16A34A",   // Owner-occupied
  rented: "#D97706",  // Rented / tenant-occupied
  unknown: "#64748B", // Occupancy unknown
  dnk: "#DC2626",     // Do Not Knock
};


export const badge = {
  pending: { bg: "#FEF3C7", fg: "#92400E", label: "Pending" },
  failed: { bg: "#FEE2E2", fg: "#991B1B", label: "Failed" },
  conflict: { bg: "#FFEDD5", fg: "#9A3412", label: "Conflict" },
  synced: { bg: "#DCFCE7", fg: "#065F46", label: "Synced" },
};
