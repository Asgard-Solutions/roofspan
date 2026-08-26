import { ArrowRight, Circle } from "lucide-react";
import { productStatus, STARTING_PRICE } from "../src/config";
import { AppMock, PhoneMock } from "./ui";

export default function Hero() {
  const status = productStatus();
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
          <h1 id="hero-title" className="h1 mt-5">Run every roofing job—from first lead to final record—in one connected operation.</h1>
          <p className="mt-5 max-w-xl text-lg text-slate-200/85">
            RoofSpan is roofing operations software that keeps your office and field crews on the same system —
            leads, properties, inspections, photos, jobs, and team access — running on your company's own Windows machine.
          </p>
          <div className="mt-8 flex flex-wrap items-center gap-3">
            <a href={status.primaryCtaHref} className="btn-primary" data-testid="hero-primary-cta"
               {...(status.primaryIsDownload ? {} : {})}>{status.primaryCtaLabel} <ArrowRight className="h-4 w-4" aria-hidden="true" /></a>
            <a href="#how-it-works" className="btn-ghost" data-testid="hero-secondary-cta">Explore the Workflow</a>
            {!status.available ? <a href="#early-access" className="text-sm font-semibold text-slate-200 underline underline-offset-4 hover:text-white" data-testid="hero-book-walkthrough">or book a walkthrough</a> : null}
          </div>
          <p className="mt-5 text-sm text-slate-300/70">Transparent pricing from <span className="font-semibold text-white">${STARTING_PRICE}/month</span> · Office + free Mobile companion</p>
        </div>
        <div className="relative flex items-center justify-center gap-4">
          <div className="w-full max-w-md"><AppMock /></div>
          <div className="-ml-16 hidden self-end sm:block"><PhoneMock /></div>
        </div>
      </div>
    </section>
  );
}
