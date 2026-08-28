import { ArrowRight, Circle } from "lucide-react";
import { productStatus, STARTING_PRICE } from "../src/config";
import { AppMock, PhoneMock } from "./ui";
import CtaButton from "./CtaButton";

export default function Hero() {
  const status = productStatus();
  const primaryHref = status.primaryCtaHref && status.primaryCtaHref.startsWith("#") ? `/${status.primaryCtaHref}` : status.primaryCtaHref;
  return (
    <section className="noise relative overflow-hidden bg-navy" aria-labelledby="hero-title">
      <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-brand/20 blur-3xl" aria-hidden="true" />
      <div className="pointer-events-none absolute -bottom-32 left-0 h-[380px] w-[380px] rounded-full bg-safety/10 blur-3xl" aria-hidden="true" />
      <div className="container-x relative grid gap-12 py-16 lg:grid-cols-[1.05fr,1fr] lg:py-24">
        <div>
          <p className="inline-flex items-center gap-2 rounded-full border border-white/15 bg-white/5 px-3 py-1 text-xs font-bold uppercase tracking-widest text-slate-100" data-testid="status-badge">
            <Circle className={`h-2.5 w-2.5 ${status.available ? "fill-emerald-400 text-emerald-400" : "fill-safety text-safety"}`} aria-hidden="true" />
            {status.label}
          </p>
          <h1 id="hero-title" className="h1 mt-5">From neighborhood to finished roof.</h1>
          <p className="mt-5 max-w-xl text-lg text-slate-200/85">
            RoofSpan helps roofing contractors identify opportunities, organize sales territories, put the right
            properties in front of their salespeople, turn field activity into leads and jobs, and connect material
            purchasing directly to ABC Supply — all in one connected operation that runs on your company's own Windows system.
          </p>
          <p className="mt-5 flex flex-wrap gap-x-2 gap-y-1 text-sm font-semibold text-slate-100" data-testid="hero-value-line">
            {["Know the property.", "Assign the rep.", "Win the job.", "Order the materials.", "Run the roof."].map((t) => (
              <span key={t} className="rounded-full bg-white/5 px-3 py-1 ring-1 ring-white/10">{t}</span>
            ))}
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <CtaButton href={primaryHref} event={status.available ? "download_click" : "early_access_cta_click"} className="btn-primary" testid="hero-primary-cta">{status.primaryCtaLabel} <ArrowRight className="h-4 w-4" aria-hidden="true" /></CtaButton>
            <a href="#how-it-works" className="btn-ghost" data-testid="hero-secondary-cta">Explore the Workflow</a>
            {!status.available ? <CtaButton href="/#early-access" event="walkthrough_request" className="text-sm font-semibold text-slate-200 underline underline-offset-4 hover:text-white" testid="hero-book-walkthrough">or book a walkthrough</CtaButton> : null}
          </div>
          <p className="mt-5 text-sm text-slate-300/70">Transparent pricing from <span className="font-semibold text-white">${STARTING_PRICE}/month</span> · Office + free Mobile companion</p>
        </div>
        <div className="relative flex items-center justify-center gap-4">
          <div className="relative w-full max-w-md">
            <AppMock src="/screenshots/office-map-satellite.jpg" label="RoofSpan Office · Territory Map" alt="RoofSpan Office satellite territory map showing thousands of properties clustered for canvass planning" priority />
            <span className="callout absolute left-3 top-14 z-10 inline-flex items-center gap-1.5 rounded-full bg-white/95 px-3 py-1.5 text-xs font-bold text-slate-ink shadow-lift ring-1 ring-black/5" style={{ animationDelay: ".35s" }} data-testid="hero-callout-properties">
              <span className="h-2 w-2 rounded-full bg-brand" aria-hidden="true" /> 8,029 properties
            </span>
            <span className="callout absolute bottom-16 left-6 z-10 inline-flex items-center gap-1.5 rounded-full bg-white/95 px-3 py-1.5 text-xs font-bold text-slate-ink shadow-lift ring-1 ring-black/5" style={{ animationDelay: ".55s" }} data-testid="hero-callout-sections">
              <span className="h-2 w-2 rounded-full bg-safety" aria-hidden="true" /> Canvass sections
            </span>
          </div>
          <div className="-ml-16 hidden self-end sm:block"><PhoneMock src="/screenshots/mobile-area.webp" alt="RoofSpan Mobile My Area — a salesperson's assigned canvass section on satellite view" /></div>
        </div>
      </div>
    </section>
  );
}
