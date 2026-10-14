import { useState, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useAuth } from "@/context/AuthContext";
import { api, apiError } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Building2, UserCog, Eye, EyeOff, Loader2, ArrowRight, ArrowLeft, CheckCircle2 } from "lucide-react";

const BG_IMAGE = "/brand/roofspan-login-bg.png";

export default function Setup() {
  const { completeSetup } = useAuth();
  const navigate = useNavigate();
  const [checking, setChecking] = useState(true);
  const [step, setStep] = useState(1);
  const [show, setShow] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  const [company, setCompany] = useState({ name: "", phone: "", email: "", address: "", license_number: "" });
  const [owner, setOwner] = useState({ owner_full_name: "", owner_email: "", owner_password: "" });

  // First-run gate: if the app is already set up, this screen must never be usable.
  useEffect(() => {
    api
      .get("/setup/status")
      .then((r) => {
        if (!r.data?.needs_setup) navigate("/login", { replace: true });
        else setChecking(false);
      })
      .catch(() => setChecking(false));
  }, [navigate]);

  const nextFromCompany = (e) => {
    e.preventDefault();
    if (!company.name.trim()) {
      toast.error("Company name is required");
      return;
    }
    setStep(2);
  };

  const submit = async (e) => {
    e.preventDefault();
    if (owner.owner_password.length < 8) {
      toast.error("Password must be at least 8 characters");
      return;
    }
    setSubmitting(true);
    try {
      const { data } = await api.post("/setup/initialize", {
        company: {
          name: company.name.trim(),
          phone: company.phone.trim(),
          email: company.email.trim(),
          address: company.address.trim(),
          license_number: company.license_number.trim(),
        },
        owner_full_name: owner.owner_full_name.trim(),
        owner_email: owner.owner_email.trim(),
        owner_password: owner.owner_password,
      });
      completeSetup(data);
      toast.success("Welcome to RoofSpan — your company is ready");
      navigate("/", { replace: true });
    } catch (err) {
      toast.error(apiError(err));
    } finally {
      setSubmitting(false);
    }
  };

  if (checking) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-slate-900" data-testid="setup-checking">
        <Loader2 className="h-6 w-6 animate-spin text-slate-300" />
      </div>
    );
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center p-4">
      <div className="absolute inset-0 bg-cover bg-center" style={{ backgroundImage: `url(${BG_IMAGE})` }} />
      <div className="absolute inset-0 bg-gradient-to-b from-slate-900/90 via-slate-900/65 to-slate-900/85" />

      <div className="relative z-10 w-full max-w-lg" data-testid="setup-card">
        <img src="/brand/roofspan-wordmark-dark.webp" alt="RoofSpan" className="mx-auto mb-6 h-16 w-auto" />

        <div className="rounded-lg border border-white/10 bg-white p-8 shadow-xl">
          <div className="mb-6 flex items-center gap-3" data-testid="setup-stepper">
            <StepPill active={step === 1} done={step > 1} index={1} icon={Building2} label="Company" />
            <div className="h-px flex-1 bg-slate-200" />
            <StepPill active={step === 2} done={false} index={2} icon={UserCog} label="Owner account" />
          </div>

          <h1 className="font-heading text-2xl font-bold tracking-tight text-slate-900">
            {step === 1 ? "Set up your company" : "Create the owner account"}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            {step === 1
              ? "This is a fresh RoofSpan installation. Let's get your business set up."
              : "The owner has full access. You can add teammates later in Admin → Users."}
          </p>

          {step === 1 ? (
            <form onSubmit={nextFromCompany} className="mt-6 space-y-4" data-testid="setup-company-form">
              <Field label="Company name" required>
                <Input
                  value={company.name}
                  onChange={(e) => setCompany({ ...company, name: e.target.value })}
                  placeholder="Acme Roofing Co."
                  required
                  data-testid="setup-company-name"
                />
              </Field>
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Phone">
                  <Input
                    value={company.phone}
                    onChange={(e) => setCompany({ ...company, phone: e.target.value })}
                    placeholder="(555) 123-4567"
                    data-testid="setup-company-phone"
                  />
                </Field>
                <Field label="Business email">
                  <Input
                    type="email"
                    value={company.email}
                    onChange={(e) => setCompany({ ...company, email: e.target.value })}
                    placeholder="office@acmeroofing.com"
                    data-testid="setup-company-email"
                  />
                </Field>
              </div>
              <Field label="Address">
                <Input
                  value={company.address}
                  onChange={(e) => setCompany({ ...company, address: e.target.value })}
                  placeholder="123 Main St, Austin, TX"
                  data-testid="setup-company-address"
                />
              </Field>
              <Field label="License number">
                <Input
                  value={company.license_number}
                  onChange={(e) => setCompany({ ...company, license_number: e.target.value })}
                  placeholder="TX-RC-000000"
                  data-testid="setup-company-license"
                />
              </Field>
              <Button type="submit" className="w-full" data-testid="setup-company-next">
                Continue <ArrowRight className="ml-1 h-4 w-4" />
              </Button>
            </form>
          ) : (
            <form onSubmit={submit} className="mt-6 space-y-4" data-testid="setup-owner-form">
              <Field label="Full name" required>
                <Input
                  value={owner.owner_full_name}
                  onChange={(e) => setOwner({ ...owner, owner_full_name: e.target.value })}
                  placeholder="Jane Doe"
                  autoComplete="name"
                  required
                  data-testid="setup-owner-name"
                />
              </Field>
              <Field label="Email" required>
                <Input
                  type="email"
                  value={owner.owner_email}
                  onChange={(e) => setOwner({ ...owner, owner_email: e.target.value })}
                  placeholder="you@acmeroofing.com"
                  autoComplete="username"
                  required
                  data-testid="setup-owner-email"
                />
              </Field>
              <Field label="Password" required>
                <div className="relative">
                  <Input
                    type={show ? "text" : "password"}
                    value={owner.owner_password}
                    onChange={(e) => setOwner({ ...owner, owner_password: e.target.value })}
                    placeholder="At least 8 characters"
                    autoComplete="new-password"
                    className="pr-10"
                    required
                    data-testid="setup-owner-password"
                  />
                  <button
                    type="button"
                    onClick={() => setShow((s) => !s)}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-700"
                    data-testid="setup-toggle-password"
                    tabIndex={-1}
                  >
                    {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
                  </button>
                </div>
              </Field>
              <div className="flex gap-3 pt-1">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setStep(1)}
                  disabled={submitting}
                  data-testid="setup-owner-back"
                >
                  <ArrowLeft className="mr-1 h-4 w-4" /> Back
                </Button>
                <Button type="submit" className="flex-1" disabled={submitting} data-testid="setup-owner-submit">
                  {submitting ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : (
                    <>
                      <CheckCircle2 className="mr-1 h-4 w-4" /> Finish setup
                    </>
                  )}
                </Button>
              </div>
            </form>
          )}
        </div>
      </div>
    </div>
  );
}

function StepPill({ active, done, index, icon: Icon, label }) {
  return (
    <div className="flex items-center gap-2">
      <div
        className={`flex h-8 w-8 items-center justify-center rounded-full text-sm font-semibold ${
          active || done ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-400"
        }`}
      >
        {done ? <CheckCircle2 className="h-4 w-4" /> : <Icon className="h-4 w-4" />}
      </div>
      <span className={`text-sm font-medium ${active || done ? "text-slate-900" : "text-slate-400"}`}>{label}</span>
    </div>
  );
}

function Field({ label, required, children }) {
  return (
    <div className="space-y-1.5">
      <Label className="text-sm font-semibold text-slate-700">
        {label} {required && <span className="text-destructive">*</span>}
      </Label>
      {children}
    </div>
  );
}
