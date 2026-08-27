import { WORKFLOW, ROLES, DIFFERENTIATORS, FAQ, BIG_THREE, MAP_TO_MATERIAL, ABC_BENEFITS } from "../src/content";
import { SectionHeading, AppMock, PhoneMock } from "./ui";
import { MapPin, Camera, FileText, Smartphone, ShoppingCart, ShieldCheck, Map, Users2, Check, ArrowRight } from "lucide-react";

const WF_ICONS = { leads: MapPin, inspections: Camera, estimates: FileText, coordination: Smartphone, materials: ShoppingCart, reporting: ShieldCheck };
const BIG3_ICONS = { property: MapPin, territory: Map, abc: ShoppingCart };

export function BigThree() {
  return (
    <section id="differentiators" className="bg-white py-20" aria-labelledby="big3-h">
      <div className="container-x">
        <SectionHeading id="big3-h" eyebrow="More than roofing CRM" title="Find the opportunity, organize the sales effort, and carry the job through to materials"
          sub="RoofSpan goes past job tracking — three capabilities set it apart from a generic roofing CRM." />
        <div className="mt-10 grid gap-4 lg:grid-cols-3">
          {BIG_THREE.map((c) => {
            const Icon = BIG3_ICONS[c.k] || MapPin;
            return (
              <div key={c.k} className="card flex flex-col p-7" data-testid={`big3-${c.k}`}>
                <span className="inline-flex h-12 w-12 items-center justify-center rounded-xl bg-brand/10"><Icon className="h-6 w-6 text-brand" aria-hidden="true" /></span>
                <h3 className="mt-5 font-display text-xl font-extrabold text-slate-ink">{c.title}</h3>
                <p className="mt-3 text-slate-body">{c.body}</p>
                {c.note ? <p className="mt-4 text-xs text-slate-muted">{c.note}</p> : null}
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}

export function MapToMaterial() {
  return (
    <section id="how-it-works" className="bg-navy py-20 noise" aria-labelledby="m2m-h">
      <div className="container-x">
        <SectionHeading id="m2m-h" dark eyebrow="From map to material order"
          title="One connected roofing process" sub="RoofSpan connects roofing sales, field work, purchasing, and production instead of making your team stitch together separate systems." />
        <ol className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {MAP_TO_MATERIAL.map((s) => (
            <li key={s.n} className="rounded-xl2 border border-white/10 bg-white/5 p-6" data-testid={`m2m-${s.n}`}>
              <span className="font-display text-3xl font-extrabold text-brand/50">{s.n}</span>
              <h3 className="mt-2 font-display text-lg font-bold text-white">{s.title}</h3>
              <p className="mt-2 text-sm text-slate-200/80">{s.body}</p>
            </li>
          ))}
        </ol>
      </div>
    </section>
  );
}

export function Product() {
  return (
    <section id="product" className="bg-slate-soft py-20" aria-labelledby="product-h">
      <div className="container-x">
        <SectionHeading id="product-h" eyebrow="The product" title="One system for the whole roofing operation" sub="Every capability below is part of RoofSpan today — no bolt-ons, no disconnected tools." />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {WORKFLOW.map((w) => {
            const Icon = WF_ICONS[w.k] || MapPin;
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

export function MobileArea() {
  return (
    <section id="sales" className="bg-white py-20" aria-labelledby="sales-h">
      <div className="container-x grid items-center gap-12 lg:grid-cols-2">
        <div>
          <SectionHeading id="sales-h" eyebrow="Sales & canvassing" title="Give every salesperson their own area"
            sub="Office defines the canvass area and assigns the rep. The rep opens My Area, works the properties, records outcomes, creates leads, and adds photos and inspections — and those changes sync back to Office." />
          <ul className="mt-6 space-y-3">
            {["Assigned canvass section on a property map", "Owner and occupancy context on each property", "Visit outcomes and Do-Not-Knock respected in the field", "Create leads and capture photos and inspections", "Built for the field: locally cached data and queued updates that sync back to Office when connectivity is available"].map((t) => (
              <li key={t} className="flex items-start gap-3 text-slate-body"><Check className="mt-0.5 h-5 w-5 shrink-0 text-brand" aria-hidden="true" />{t}</li>
            ))}
          </ul>
        </div>
        <div className="flex items-center justify-center gap-4">
          <div className="w-full max-w-sm"><AppMock src="/screenshots/office-map.jpg" label="RoofSpan Office · Territory Map" alt="RoofSpan Office territory map with canvass sections and property pins" /></div>
          <div className="hidden self-end sm:block"><PhoneMock src="/screenshots/mobile-area.png" alt="RoofSpan Mobile My Area — assigned canvass section with property pins" /></div>
        </div>
      </div>
    </section>
  );
}

export function AbcSupply() {
  return (
    <section id="abc" className="bg-slate-soft py-20" aria-labelledby="abc-h">
      <div className="container-x">
        <SectionHeading id="abc-h" eyebrow="RoofSpan + ABC Supply" title="Price and order materials without leaving RoofSpan"
          sub="Connect your ABC Supply account and bring product selection, customer-specific pricing, purchasing, and order tracking closer to the roofing job." />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {ABC_BENEFITS.map((b) => (
            <div key={b} className="card flex items-start gap-3 p-5" data-testid="abc-benefit">
              <ShoppingCart className="mt-0.5 h-5 w-5 shrink-0 text-brand" aria-hidden="true" />
              <p className="text-slate-body">{b}</p>
            </div>
          ))}
        </div>
        <p className="mt-6 max-w-2xl text-sm text-slate-muted">Account-specific pricing reflects your ABC Supply pricing; it does not by itself confirm product availability.</p>
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
        <SectionHeading id="diff-h" dark eyebrow="Why RoofSpan" title="What sets RoofSpan apart" />
        <div className="mt-10 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
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

export function DataSecurity() {
  const layers = [
    { t: "RoofSpan Office", d: "Installs and runs on your company's own Windows machine. Your operational PostgreSQL roofing database lives with your installation." },
    { t: "RoofSpan Mobile", d: "Free companion apps that securely pair with your Office installation so field crews can work while away from the office." },
  ];
  return (
    <section id="data" className="bg-white py-20" aria-labelledby="data-h">
      <div className="container-x">
        <SectionHeading id="data-h" eyebrow="Data & security" title="Your operation runs on a system you control" sub="RoofSpan is built around two clearly separate pieces. Here's how they fit together." />
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
    <section id="faq" className="bg-slate-soft py-20" aria-labelledby="faq-h">
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
