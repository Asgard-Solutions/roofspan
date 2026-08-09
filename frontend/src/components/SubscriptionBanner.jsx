import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { AlertTriangle } from "lucide-react";

// Escalating payment-grace + suspended banner shown "loud and proud" in the Office header,
// without obscuring ordinary business work during GRACE.
export function SubscriptionBanner() {
  const [sub, setSub] = useState(null);
  const navigate = useNavigate();

  useEffect(() => {
    let alive = true;
    const load = () => api.get("/subscription").then((r) => alive && setSub(r.data)).catch(() => {});
    load();
    const t = setInterval(load, 60000);
    return () => { alive = false; clearInterval(t); };
  }, []);

  if (!sub) return null;
  const state = sub.state;
  if (state !== "GRACE" && state !== "SUSPENDED" && state !== "CANCELLED" && !sub.seat_action_required) return null;

  let tone = "amber", title = "", msg = "";
  if (state === "SUSPENDED" || state === "CANCELLED") {
    tone = "red";
    title = "RoofSpan access is restricted";
    msg = "Your subscription payment was not completed. Your company data is safe. Update billing to restore access.";
  } else if (state === "GRACE") {
    const day = sub.grace_day || 1;
    tone = day >= 5 ? "red" : "amber";
    if (day >= 5) { title = "RoofSpan access will be restricted soon"; msg = "Your subscription payment is still unsuccessful. Update billing now to avoid interruption when the 7-day grace period ends."; }
    else if (day >= 3) { title = "RoofSpan payment still unresolved"; msg = "Your payment has not been successfully processed. Please update your billing information to avoid losing access."; }
    else { title = "Payment failed — action required"; msg = "We were unable to process your RoofSpan subscription payment. Update your billing information to avoid interruption."; }
  } else if (sub.seat_action_required) {
    title = "Seat limit exceeded";
    msg = `You have ${sub.active_over_by} more active user(s) than your licensed seats. Add seats or deactivate users.`;
  }

  const cls = tone === "red" ? "bg-red-600 text-white" : "bg-amber-500 text-white";
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 px-4 py-2 ${cls}`} data-testid="subscription-header-banner">
      <div className="flex items-center gap-2 text-sm">
        <AlertTriangle className="h-4 w-4 shrink-0" />
        <span className="font-semibold">{title}.</span>
        <span className="hidden opacity-95 sm:inline">{msg}</span>
      </div>
      <button
        onClick={() => navigate("/admin/subscription")}
        className="rounded-md bg-white/20 px-3 py-1 text-xs font-semibold hover:bg-white/30"
        data-testid="banner-manage-billing"
      >
        Manage Billing
      </button>
    </div>
  );
}
