import { useEffect, useState, useCallback } from "react";
import { api, apiError } from "@/lib/api";
import { PageHeader } from "@/components/PageHeader";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { RefreshCw, CreditCard, UserPlus, ShieldCheck, AlertTriangle, CheckCircle2, XCircle } from "lucide-react";

const STATE_STYLES = {
  ACTIVE: { cls: "bg-emerald-50 text-emerald-700", Icon: CheckCircle2, color: "text-emerald-600" },
  GRACE: { cls: "bg-amber-50 text-amber-700", Icon: AlertTriangle, color: "text-amber-600" },
  SUSPENDED: { cls: "bg-red-50 text-red-700", Icon: XCircle, color: "text-red-600" },
  CANCELLED: { cls: "bg-red-50 text-red-700", Icon: XCircle, color: "text-red-600" },
};

function Stat({ label, value, testid }) {
  return (
    <div className="rounded-md border border-border bg-white p-4" data-testid={testid}>
      <div className="text-xs uppercase tracking-wide text-slate-400">{label}</div>
      <div className="mt-1 text-2xl font-semibold text-slate-900">{value}</div>
    </div>
  );
}

export default function Subscription() {
  const [sub, setSub] = useState(null);
  const [loading, setLoading] = useState(false);
  const [busy, setBusy] = useState("");

  const load = useCallback(() => {
    setLoading(true);
    api.get("/subscription").then((r) => setSub(r.data)).catch((e) => toast.error(apiError(e))).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  const refresh = async () => {
    setBusy("refresh");
    try {
      await api.post("/subscription/refresh");
      toast.success("Subscription refreshed");
      load();
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };

  const openBilling = async (kind) => {
    setBusy(kind);
    try {
      const path = kind === "checkout" ? "/billing/checkout" : "/billing/portal-url";
      const r = kind === "checkout" ? await api.post(path) : await api.get(path);
      if (r.data.configured && r.data.url) {
        window.open(r.data.url, "_blank", "noopener");
      } else {
        toast.message("Billing not connected yet", { description: r.data.message || "Configure your RevenueCat/Stripe account to enable hosted billing." });
      }
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(""); }
  };

  const st = STATE_STYLES[sub?.state] || STATE_STYLES.SUSPENDED;
  const StateIcon = st.Icon;

  return (
    <div>
      <PageHeader
        title="Subscription"
        description="RoofSpan licensing and seat management"
        testid="page-subscription"
        actions={
          <Button variant="outline" size="sm" onClick={refresh} disabled={busy === "refresh"} data-testid="subscription-refresh">
            <RefreshCw className={`h-4 w-4 ${busy === "refresh" ? "animate-spin" : ""}`} /> Refresh
          </Button>
        }
      />
      <div className="p-6 sm:p-8">
        {sub && (sub.state === "SUSPENDED" || sub.state === "CANCELLED") && (
          <div className="mb-6 flex items-start gap-3 rounded-md border border-red-200 bg-red-50 p-4" data-testid="subscription-lapse-banner">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-red-600" />
            <div>
              <div className="font-semibold text-red-800">RoofSpan subscription requires attention</div>
              <div className="text-sm text-red-700">Your subscription is past due. Your company data is safe, but normal RoofSpan functionality is temporarily unavailable. Update your billing information to restore access.</div>
              <Button size="sm" className="mt-3 gap-2 bg-red-600 hover:bg-red-700" onClick={() => openBilling("portal")} disabled={busy === "portal"} data-testid="reactivate-button">
                <CreditCard className="h-4 w-4" /> Update Billing / Reactivate RoofSpan
              </Button>
            </div>
          </div>
        )}

        {sub && sub.state === "GRACE" && (
          <div className="mb-6 flex items-start gap-3 rounded-md border border-amber-200 bg-amber-50 p-4" data-testid="subscription-grace-banner">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div className="text-sm text-amber-800">A payment issue was detected. RoofSpan continues to work during a grace period — please update billing to avoid interruption.</div>
          </div>
        )}

        {sub && sub.seat_action_required && (
          <div className="mb-6 flex items-start gap-3 rounded-md border border-amber-200 bg-amber-50 p-4" data-testid="seat-action-banner">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-amber-600" />
            <div className="text-sm text-amber-800">
              You have <strong>{sub.active_over_by}</strong> more active user{sub.active_over_by === 1 ? "" : "s"} than your licensed seats.
              Add seats, or deactivate users, to resolve this. No users have been disabled automatically.
            </div>
          </div>
        )}

        <div className="mb-6 flex items-center gap-3" data-testid="subscription-status-row">
          <ShieldCheck className="h-5 w-5 text-slate-400" />
          <span className="text-sm text-slate-500">Subscription status</span>
          <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ${st.cls}`} data-testid="subscription-state-badge">
            <StateIcon className={`h-3.5 w-3.5 ${st.color}`} /> {sub?.state || (loading ? "…" : "—")}
          </span>
          {sub?.cancel_at_period_end && sub?.current_period_end && (
            <span className="text-xs font-medium text-amber-600" data-testid="cancels-on-note">
              Cancels on {new Date(sub.current_period_end).toLocaleDateString()}
            </span>
          )}
          {sub && !sub.online && <span className="text-xs text-slate-400" data-testid="offline-note">(using cached entitlement — offline)</span>}
        </div>

        {sub?.scheduled_seats != null && sub?.scheduled_seats_at && (
          <div className="mb-6 rounded-md border border-slate-200 bg-slate-50 p-4 text-sm text-slate-700" data-testid="scheduled-seat-note">
            <strong>{sub.seats_licensed} licensed seats.</strong> Scheduled to reduce to <strong>{sub.scheduled_seats}</strong> on {new Date(sub.scheduled_seats_at).toLocaleDateString()}.
            {sub.active_users > sub.scheduled_seats && (
              <div className="mt-1 text-amber-700" data-testid="scheduled-compliance-warning">
                You currently have {sub.active_users} active users. Disable at least {sub.active_users - sub.scheduled_seats} before the new limit takes effect — no users are disabled automatically.
              </div>
            )}
          </div>
        )}

        <div className="grid max-w-3xl grid-cols-1 gap-4 sm:grid-cols-3">
          <Stat label="Licensed Seats" value={sub?.seats_licensed ?? "—"} testid="stat-licensed-seats" />
          <Stat label="Active Users" value={sub?.active_users ?? "—"} testid="stat-active-users" />
          <Stat label="Available Seats" value={sub?.available_seats ?? "—"} testid="stat-available-seats" />
        </div>

        <div className="mt-6 flex flex-wrap gap-3">
          <Button variant="outline" className="gap-2" onClick={() => openBilling("portal")} disabled={busy === "portal"} data-testid="manage-billing-button">
            <CreditCard className="h-4 w-4" /> Manage Billing
          </Button>
          <Button className="gap-2 bg-orange-600 hover:bg-orange-700" onClick={() => openBilling("checkout")} disabled={busy === "checkout"} data-testid="add-seats-button">
            <UserPlus className="h-4 w-4" /> Add Seats
          </Button>
        </div>

        <p className="mt-4 max-w-3xl text-xs text-slate-400" data-testid="seat-bounds-note">
          Licensed seats range from {sub?.min_seats ?? 5} to {sub?.max_seats ?? 50}. The Owner counts as a licensed seat; deactivated users do not consume a seat.
        </p>
      </div>
    </div>
  );
}
