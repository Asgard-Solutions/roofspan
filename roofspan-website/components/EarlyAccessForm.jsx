"use client";
import { useState } from "react";
import { LEAD_ENDPOINT, CONTACT_EMAIL } from "../src/config";
import { trackEvent } from "../src/analytics";

const TEAM_SIZES = ["1–5", "6–15", "16–40", "41–100", "100+"];

function buildMailto(data) {
  const subject = encodeURIComponent(`RoofSpan early access — ${data.company || data.name}`);
  const body = encodeURIComponent(
    `Name: ${data.name}\nWork email: ${data.email}\nCompany: ${data.company}\nTeam size: ${data.teamSize}\n\n${data.message || ""}`
  );
  return `mailto:${CONTACT_EMAIL}?subject=${subject}&body=${body}`;
}

export default function EarlyAccessForm() {
  const [values, setValues] = useState({ name: "", email: "", company: "", teamSize: TEAM_SIZES[0], message: "", consent: false, company_website: "" });
  const [errors, setErrors] = useState({});
  const [state, setState] = useState("idle"); // idle | submitting | success | mailto | error
  const set = (k) => (e) => setValues((v) => ({ ...v, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  function validate() {
    const e = {};
    if (!values.name.trim()) e.name = "Please enter your name.";
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(values.email)) e.email = "Please enter a valid work email.";
    if (!values.company.trim()) e.company = "Please enter your company.";
    if (!values.consent) e.consent = "Please confirm you'd like us to contact you.";
    setErrors(e);
    return Object.keys(e).length === 0;
  }

  async function onSubmit(ev) {
    ev.preventDefault();
    if (values.company_website) return; // honeypot: silently drop bots
    if (!validate()) return;
    // No approved endpoint configured -> transparent mailto fallback (never a fake success).
    if (!LEAD_ENDPOINT) {
      trackEvent("early_access_submit", { method: "mailto", team_size: values.teamSize });
      window.location.href = buildMailto(values);
      setState("mailto");
      return;
    }
    setState("submitting");
    try {
      const res = await fetch(LEAD_ENDPOINT, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: values.name, email: values.email, company: values.company, teamSize: values.teamSize, message: values.message }),
      });
      if (!res.ok) throw new Error(String(res.status));
      trackEvent("early_access_submit", { method: "endpoint", team_size: values.teamSize });
      setState("success");
    } catch (err) {
      setState("error");
    }
  }

  const field = "w-full rounded-lg border px-4 py-3 text-base";
  const ok = "border-slate-line focus:border-brand";
  const bad = "border-red-500";

  return (
    <form onSubmit={onSubmit} noValidate aria-labelledby="ea-title" data-testid="early-access-form" className="card bg-white p-6 sm:p-8">
      <h3 id="ea-title" className="font-display text-2xl font-bold text-slate-ink">Join early access</h3>
      <p className="mt-1 text-slate-body">Tell us about your roofing company and we'll be in touch about getting you set up.</p>

      {state === "success" && <p role="status" data-testid="form-success" className="mt-4 rounded-lg bg-emerald-50 px-4 py-3 font-semibold text-emerald-800">Thanks — your request is in. We'll email you shortly.</p>}
      {state === "mailto" && <p role="status" data-testid="form-mailto" className="mt-4 rounded-lg bg-brand/10 px-4 py-3 font-semibold text-brand">We've opened your email app to send your details to {CONTACT_EMAIL}. If nothing opened, email us directly.</p>}
      {state === "error" && <p role="alert" data-testid="form-error" className="mt-4 rounded-lg bg-red-50 px-4 py-3 font-semibold text-red-800">Something went wrong. Please email {CONTACT_EMAIL} and we'll take care of it.</p>}

      <div className="mt-5 grid gap-4 sm:grid-cols-2">
        <div>
          <label htmlFor="ea-name" className="text-sm font-semibold text-slate-body">Name</label>
          <input id="ea-name" name="name" value={values.name} onChange={set("name")} className={`${field} ${errors.name ? bad : ok}`} aria-invalid={!!errors.name} aria-describedby={errors.name ? "err-name" : undefined} data-testid="field-name" />
          {errors.name && <p id="err-name" role="alert" className="mt-1 text-sm text-red-600">{errors.name}</p>}
        </div>
        <div>
          <label htmlFor="ea-email" className="text-sm font-semibold text-slate-body">Work email</label>
          <input id="ea-email" name="email" type="email" value={values.email} onChange={set("email")} className={`${field} ${errors.email ? bad : ok}`} aria-invalid={!!errors.email} aria-describedby={errors.email ? "err-email" : undefined} data-testid="field-email" />
          {errors.email && <p id="err-email" role="alert" className="mt-1 text-sm text-red-600">{errors.email}</p>}
        </div>
        <div>
          <label htmlFor="ea-company" className="text-sm font-semibold text-slate-body">Company</label>
          <input id="ea-company" name="company" value={values.company} onChange={set("company")} className={`${field} ${errors.company ? bad : ok}`} aria-invalid={!!errors.company} aria-describedby={errors.company ? "err-company" : undefined} data-testid="field-company" />
          {errors.company && <p id="err-company" role="alert" className="mt-1 text-sm text-red-600">{errors.company}</p>}
        </div>
        <div>
          <label htmlFor="ea-team" className="text-sm font-semibold text-slate-body">Approximate team size</label>
          <select id="ea-team" name="teamSize" value={values.teamSize} onChange={set("teamSize")} className={`${field} ${ok}`} data-testid="field-teamsize">
            {TEAM_SIZES.map((t) => <option key={t}>{t}</option>)}
          </select>
        </div>
      </div>
      <div className="mt-4">
        <label htmlFor="ea-message" className="text-sm font-semibold text-slate-body">Message <span className="font-normal text-slate-muted">(optional)</span></label>
        <textarea id="ea-message" name="message" rows={3} value={values.message} onChange={set("message")} className={`${field} ${ok}`} data-testid="field-message" />
      </div>
      {/* Honeypot: hidden from users & AT; bots that fill it are dropped */}
      <div aria-hidden="true" className="hidden"><label>Company website<input tabIndex={-1} autoComplete="off" name="company_website" value={values.company_website} onChange={set("company_website")} /></label></div>

      <div className="mt-4 flex items-start gap-3">
        <input id="ea-consent" type="checkbox" checked={values.consent} onChange={set("consent")} className="mt-1 h-5 w-5 accent-brand" aria-invalid={!!errors.consent} aria-describedby={errors.consent ? "err-consent" : undefined} data-testid="field-consent" />
        <label htmlFor="ea-consent" className="text-sm text-slate-body">I'd like RoofSpan to contact me about early access.</label>
      </div>
      {errors.consent && <p id="err-consent" role="alert" className="mt-1 text-sm text-red-600">{errors.consent}</p>}

      <button type="submit" className="btn-primary mt-6 w-full" disabled={state === "submitting"} data-testid="form-submit">
        {state === "submitting" ? "Sending…" : "Request early access"}
      </button>
    </form>
  );
}
