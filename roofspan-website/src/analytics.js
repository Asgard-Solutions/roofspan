// Lightweight, provider-agnostic analytics helper. IDs come from env only (never hard-coded):
//   NEXT_PUBLIC_GA_MEASUREMENT_ID  (GA4, e.g. G-XXXXXXX)
//   NEXT_PUBLIC_GTM_ID             (Google Tag Manager, e.g. GTM-XXXXXXX)
// When neither is configured, tracking is a no-op (no network, no console noise).

export const GA_MEASUREMENT_ID = process.env.NEXT_PUBLIC_GA_MEASUREMENT_ID || "";
export const GTM_ID = process.env.NEXT_PUBLIC_GTM_ID || "";
export const ANALYTICS_ENABLED = !!(GA_MEASUREMENT_ID || GTM_ID);

// Fire a semantic event to GA4 (gtag) and/or GTM (dataLayer). Safe on the server / when disabled.
export function trackEvent(event, params = {}) {
  if (typeof window === "undefined") return;
  try {
    if (window.gtag) window.gtag("event", event, params);
    if (window.dataLayer) window.dataLayer.push({ event, ...params });
  } catch {
    /* analytics must never break the UI */
  }
}
