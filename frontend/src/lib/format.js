export const money = (n) =>
  (Number(n) || 0).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const shortDate = (d) => (d ? new Date(d).toLocaleDateString() : "—");

// Job schedule dates are calendar days: read the stored YYYY-MM-DD so time zones never shift the day.
export const dayOnly = (d) => {
  if (!d) return null;
  const [y, m, day] = String(d).slice(0, 10).split("-").map(Number);
  return new Date(y, m - 1, day);
};
export const shortDay = (d) => (d ? dayOnly(d).toLocaleDateString() : "—");
export const dayToIso = (date) => {
  if (!date) return null;
  const p = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${p(date.getMonth() + 1)}-${p(date.getDate())}T12:00:00Z`;
};
export const dayCount = (from, to) => (from && to ? Math.round((to - from) / 86400000) + 1 : from ? 1 : 0);
