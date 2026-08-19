import { useEffect, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { API_BASE, api, apiError, setToken, getToken } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { HardHat, Building2, ShieldCheck, CreditCard, Loader2, ExternalLink, CheckCircle2 } from "lucide-react";

const BG_IMAGE = "/brand/roofspan-login-bg.png";

function Shell({ icon: Icon, title, subtitle, children }) {
  return (
    <div className="relative flex min-h-screen items-center justify-center p-4">
      <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: `url(${BG_IMAGE})` }} />
      <div className="absolute inset-0 bg-gradient-to-b from-slate-900/85 via-slate-900/60 to-slate-900/80" />
      <div className="relative z-10 w-full max-w-lg" data-testid="setup-card">
        <img src="/brand/roofspan-wordmark-dark.webp" alt="RoofSpan" className="mx-auto mb-6 h-14 w-auto" />
        <div className="rounded-lg border border-white/10 bg-white p-8 shadow-xl">
          <div className="mb-5 flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-md bg-orange-50">
              <Icon className="h-5 w-5 text-orange-600" />
            </div>
            <div>
              <h1 className="font-heading text-xl font-bold tracking-tight text-slate-900">{title}</h1>
              {subtitle && <p className="text-sm text-slate-500">{subtitle}</p>}
            </div>
          </div>
          {children}
        </div>
        <p className="mt-4 text-center text-xs text-white/70">Set up your local RoofSpan Office installation.</p>
      </div>
    </div>
  );
}

function Field({ label, ...props }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-sm font-semibold text-slate-700">{label}</Label>
      <Input {...props} />
    </div>
  );
}

export default function Setup() {
  const [phase, setPhase] = useState("loading"); // loading | company | signin | payment | done
  const [meta, setMeta] = useState({ seats: 5, monthly_price_usd: 245 });
  const [busy, setBusy] = useState(false);

  // company + owner form
  const [company, setCompany] = useState({ name: "", email: "", phone: "", address: "" });
  const [owner, setOwner] = useState({ full_name: "", email: "", password: "", confirm_password: "" });
  // sign-in (returning during payment-pending)
  const [creds, setCreds] = useState({ email: "", password: "" });
  // payment step
  const [pay, setPay] = useState({ checkout_url: "", can_simulate: false });

  const loadStatus = async () => {
    try {
      const { data } = await axios.get(`${API_BASE}/setup/status`);
      setMeta({ seats: data.seats, monthly_price_usd: data.monthly_price_usd });
      if (data.state === "initialized") {
        window.location.href = "/";
        return;
      }
      if (data.state === "setup_required") {
        setPhase("company");
      } else {
        // owner_created / payment_required
        setPhase(getToken() ? "payment" : "signin");
      }
    } catch (e) {
      toast.error(apiError(e));
      setPhase("company");
    }
  };

  useEffect(() => { loadStatus(); }, []);

  const submitCompany = async (e) => {
    e.preventDefault();
    if (owner.password !== owner.confirm_password) { toast.error("Passwords do not match"); return; }
    setBusy(true);
    try {
      const { data } = await axios.post(`${API_BASE}/setup/bootstrap`, {
        company: { name: company.name.trim(), email: company.email.trim(), phone: company.phone.trim(), address: company.address.trim() },
        owner: { full_name: owner.full_name.trim(), email: owner.email.trim(), password: owner.password, confirm_password: owner.confirm_password },
      });
      setToken(data.access_token);
      toast.success("Company and Owner created");
      setPhase("payment");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const submitSignin = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await axios.post(`${API_BASE}/auth/login`, { email: creds.email.trim(), password: creds.password });
      setToken(data.access_token);
      setPhase("payment");
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const startCheckout = async () => {
    setBusy(true);
    try {
      const { data } = await api.post("/setup/checkout");
      setPay({ checkout_url: data.checkout_url, can_simulate: false });
      setMeta({ seats: data.seats, monthly_price_usd: data.monthly_price_usd });
      await checkStatus(true);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const checkStatus = async (silent = false) => {
    setBusy(true);
    try {
      const { data } = await api.get("/setup/payment-status");
      if (data.state === "initialized") {
        setPhase("done");
        toast.success("Subscription active — RoofSpan is ready");
        setTimeout(() => { window.location.href = "/"; }, 1200);
        return;
      }
      setPay((p) => ({ ...p, checkout_url: data.checkout_url || p.checkout_url, can_simulate: !!data.can_simulate }));
      if (!silent) toast.message("Payment not confirmed yet", { description: "Complete checkout, then check again." });
    } catch (e) { if (!silent) toast.error(apiError(e)); } finally { setBusy(false); }
  };

  const simulatePay = async () => {
    setBusy(true);
    try {
      await api.post("/setup/dev/pay");
      await checkStatus(true);
    } catch (e) { toast.error(apiError(e)); } finally { setBusy(false); }
  };

  useEffect(() => { if (phase === "payment" && !pay.checkout_url) { startCheckout(); } // eslint-disable-next-line
  }, [phase]);

  if (phase === "loading") {
    return <Shell icon={HardHat} title="RoofSpan Office"><div className="flex justify-center py-6"><Loader2 className="h-6 w-6 animate-spin text-slate-400" /></div></Shell>;
  }

  if (phase === "company") {
    return (
      <Shell icon={Building2} title="Welcome to RoofSpan" subtitle="Step 1 of 2 — Your company & owner account">
        <form onSubmit={submitCompany} className="space-y-4" data-testid="setup-company-form">
          <div className="text-xs font-semibold uppercase tracking-wider text-slate-400">Company</div>
          <Field label="Company name" value={company.name} onChange={(e) => setCompany({ ...company, name: e.target.value })} placeholder="Acme Roofing Co." required data-testid="setup-company-name" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Business email" type="email" value={company.email} onChange={(e) => setCompany({ ...company, email: e.target.value })} placeholder="office@acme.com" required data-testid="setup-company-email" />
            <Field label="Phone" value={company.phone} onChange={(e) => setCompany({ ...company, phone: e.target.value })} placeholder="(555) 123-4567" data-testid="setup-company-phone" />
          </div>
          <Field label="Address" value={company.address} onChange={(e) => setCompany({ ...company, address: e.target.value })} placeholder="123 Main St, City, State" data-testid="setup-company-address" />

          <div className="pt-2 text-xs font-semibold uppercase tracking-wider text-slate-400">Owner account (licensed seat #1)</div>
          <Field label="Full name" value={owner.full_name} onChange={(e) => setOwner({ ...owner, full_name: e.target.value })} placeholder="Jane Owner" required data-testid="setup-owner-name" />
          <Field label="Email" type="email" value={owner.email} onChange={(e) => setOwner({ ...owner, email: e.target.value })} placeholder="jane@acme.com" required data-testid="setup-owner-email" />
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="Password" type="password" value={owner.password} onChange={(e) => setOwner({ ...owner, password: e.target.value })} placeholder="At least 8 characters" required data-testid="setup-owner-password" />
            <Field label="Confirm password" type="password" value={owner.confirm_password} onChange={(e) => setOwner({ ...owner, confirm_password: e.target.value })} placeholder="Re-enter password" required data-testid="setup-owner-confirm" />
          </div>
          <Button type="submit" className="w-full" disabled={busy} data-testid="setup-company-submit">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Continue to subscription"}
          </Button>
        </form>
      </Shell>
    );
  }

  if (phase === "signin") {
    return (
      <Shell icon={ShieldCheck} title="Continue setup" subtitle="Sign in to finish your subscription">
        <form onSubmit={submitSignin} className="space-y-4" data-testid="setup-signin-form">
          <Field label="Email" type="email" value={creds.email} onChange={(e) => setCreds({ ...creds, email: e.target.value })} placeholder="you@company.com" required data-testid="setup-signin-email" />
          <Field label="Password" type="password" value={creds.password} onChange={(e) => setCreds({ ...creds, password: e.target.value })} placeholder="••••••••" required data-testid="setup-signin-password" />
          <Button type="submit" className="w-full" disabled={busy} data-testid="setup-signin-submit">
            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "Continue"}
          </Button>
        </form>
      </Shell>
    );
  }

  if (phase === "done") {
    return (
      <Shell icon={CheckCircle2} title="RoofSpan is ready" subtitle="Your subscription is active">
        <div className="flex flex-col items-center py-4 text-center" data-testid="setup-done">
          <CheckCircle2 className="h-10 w-10 text-emerald-500" />
          <p className="mt-3 text-sm text-slate-600">{meta.seats} licensed seats activated. Taking you to RoofSpan Office…</p>
        </div>
      </Shell>
    );
  }

  // payment
  return (
    <Shell icon={CreditCard} title="Complete your subscription" subtitle={`RoofSpan will be ready after your initial ${meta.seats}-seat subscription is confirmed.`}>
      <div className="space-y-4" data-testid="setup-payment">
        <div className="rounded-md border border-border bg-slate-50 p-4">
          <div className="flex items-baseline justify-between">
            <span className="text-sm font-medium text-slate-700">RoofSpan — {meta.seats} seats</span>
            <span className="font-heading text-2xl font-bold text-slate-900" data-testid="setup-price">${meta.monthly_price_usd}<span className="text-sm font-medium text-slate-500">/mo</span></span>
          </div>
          <p className="mt-1 text-xs text-slate-500">${49} per licensed seat / month · 5-seat minimum. You can add more seats later from Administration → Subscription.</p>
        </div>

        <Button className="w-full" disabled={busy || !pay.checkout_url} onClick={() => pay.checkout_url && window.open(pay.checkout_url, "_blank")} data-testid="setup-open-checkout">
          <ExternalLink className="mr-2 h-4 w-4" /> Open secure checkout
        </Button>
        <Button variant="outline" className="w-full" disabled={busy} onClick={() => checkStatus(false)} data-testid="setup-check-status">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : "I've completed payment — check status"}
        </Button>

        {pay.can_simulate && (
          <Button variant="ghost" className="w-full text-slate-500" disabled={busy} onClick={simulatePay} data-testid="setup-simulate-pay">
            Simulate successful payment (dev)
          </Button>
        )}
        <p className="text-center text-xs text-slate-400">Payment is processed securely by our payment provider. RoofSpan never stores your card details.</p>
      </div>
    </Shell>
  );
}
