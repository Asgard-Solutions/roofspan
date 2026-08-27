import { WORKFLOW, STEPS, ROLES, DIFFERENTIATORS, FAQ } from "../src/content";
import { SectionHeading, AppMock, PhoneMock } from "./ui";
import { ClipboardList, Camera, FileText, Users2, Boxes, ShieldCheck } from "lucide-react";

const WF_ICONS = { leads: ClipboardList, inspections: Camera, estimates: FileText, coordination: Users2, materials: Boxes, reporting: ShieldCheck };

export function Product() {
  return (
    <section id="product" className="bg-white py-20" aria-labelledby="product-h">
      <div className="container-x">
        <SectionHeading id="product-h" eyebrow="The product" title="One system for the whole roofing job lifecycle" sub="Every capability below is part of RoofSpan today — no bolt-ons, no disconnected tools." />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {WORKFLOW.map((w) => {
            const Icon = WF_ICONS[w.k] || ClipboardList;
            return (
              <div key={w.k} className="card p-6" data-testid={`workflow-${w.k}`}>
                <span className="inline-flex h-11 w-11 items-center justify-center rounded-xl bg-brand/10"><Icon className="h-5 w-5 text-brand" aria-hidden="true" /></span>
                <h3 className="mt-4 font-display text-lg font-bold text-slate-ink">{w.title}</h3>
                <p className="mt-2 text-slate-body">{w.body}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export function HowItWorks() {
  return (
    <section id="how-it-works" className="bg-slate-soft py-20" aria-labelledby="how-h">
      <div className="container-x">
        <SectionHeading id="how-h" eyebrow="How it works" title="Office and field, connected in four steps" />
        <ol className="mt-10 grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          {STEPS.map((s) => (
            <li key={s.n} className="card p-6" data-testid={`step-${s.n}`}>
              <span className="font-display text-3xl font-extrabold text-brand/30">{s.n}</span>
              <h3 className="mt-2 font-display text-lg font-bold text-slate-ink">{s.title}</h3>
              <p className="mt-2 text-slate-body">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function Roles() {
  return (
    <section id="why" className="bg-white py-20" aria-labelledby="roles-h">
      <div className="container-x">
        <SectionHeading id="roles-h" eyebrow="Built for your whole team" title="Value for every role in a roofing company" />
        <div className="mt-10 grid gap-4 sm:grid-cols-2">
          {ROLES.map((r) => (
            <div key={r.role} className="card p-6" data-testid={`role-${r.role.split(" ")[0].toLowerCase()}`}>
              <h3 className="font-display text-lg font-bold text-slate-ink">{r.role}</h3>
              <p className="mt-2 text-slate-body">{r.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Differentiators() {
  return (
    <section className="bg-navy py-20 noise" aria-labelledby="diff-h">
      <div className="container-x">
        <SectionHeading id="diff-h" dark eyebrow="Why RoofSpan" title="Roofing-specific, connected, and yours" />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {DIFFERENTIATORS.map((d) => (
            <div key={d.title} className="rounded-xl2 border border-white/10 bg-white/5 p-6">
              <h3 className="font-display text-lg font-bold text-white">{d.title}</h3>
              <p className="mt-2 text-slate-200/80">{d.body}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function ProductProof() {
  return (
    <section className="bg-slate-soft py-20" aria-labelledby="proof-h">
      <div className="container-x grid items-center gap-12 lg:grid-cols-2">
        <div>
          <SectionHeading id="proof-h" eyebrow="Product proof" title="Built around the real roofing workflow" sub="These are real screens from RoofSpan Office and the RoofSpan Mobile field app — the same tools your office and crews use every day." />
          <ul className="mt-6 space-y-3">
            {["Jobs, leads, and properties in one place", "Inspections and photos tied to the right job", "Office and free Mobile companion in sync"].map((t) => (
              <li key={t} className="flex items-start gap-3 text-slate-body"><span className="mt-1 h-2 w-2 shrink-0 rounded-full bg-safety" aria-hidden="true" />{t}</li>
            ))}
          </ul>
        </div>
        <div className="flex items-center justify-center gap-4">
          <div className="w-full max-w-sm"><AppMock src="/screenshots/office-jobs.png" label="RoofSpan Office · Jobs" alt="RoofSpan Office jobs list with job numbers, scope, status, and value" /></div>
          <div className="hidden self-end sm:block"><PhoneMock src="/screenshots/mobile-leads.png" alt="RoofSpan Mobile leads list with field lead statuses" /></div>
        </div>
      </div>
    </section>
  );
}

export function DataSecurity() {
  const layers = [
    { t: "RoofSpan Office", d: "Installs and runs on your company's own Windows machine. Your operational roofing database lives with your installation." },
    { t: "RoofSpan Mobile", d: "Free companion apps that securely pair with your Office installation so field crews can work while away from the office." },
  ];
  return (
    <section id="data" className="bg-white py-20" aria-labelledby="data-h">
      <div className="container-x">
        <SectionHeading id="data-h" eyebrow="Security & data" title="Your operation runs on a system you control" sub="RoofSpan is built around two clearly separate pieces. Here's how they fit together." />
        <div className="mt-10 grid gap-4 md:grid-cols-2">
          {layers.map((l) => (
            <div key={l.t} className="card p-6" data-testid={`data-${l.t.split(" ")[1] ? l.t.split(" ")[1].toLowerCase() : "site"}`}>
              <h3 className="font-display text-lg font-bold text-slate-ink">{l.t}</h3>
              <p className="mt-2 text-slate-body">{l.d}</p>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function Faq() {
  return (
    <section className="bg-slate-soft py-20" aria-labelledby="faq-h">
      <div className="container-x max-w-3xl">
        <SectionHeading id="faq-h" eyebrow="FAQ" title="Common questions" />
        <div className="mt-8 divide-y divide-slate-line">
          {FAQ.map((f, i) => (
            <details key={i} className="group py-4" data-testid={`faq-${i}`}>
              <summary className="cursor-pointer list-none font-display text-lg font-semibold text-slate-ink [&::-webkit-details-marker]:hidden">{f.q}</summary>
              <p className="mt-3 text-slate-body">{f.a}</p>
            </details>
          ))}
        </div>
      </div>
    </section>
  );
}
