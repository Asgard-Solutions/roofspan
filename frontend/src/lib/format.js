export const money = (n) =>
  (Number(n) || 0).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const shortDate = (d) => (d ? new Date(d).toLocaleDateString() : "—");
