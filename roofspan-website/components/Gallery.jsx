"use client";
import { useState, useEffect, useCallback } from "react";
import { X, ChevronLeft, ChevronRight, Expand } from "lucide-react";
import { SectionHeading } from "./ui";

const OFFICE = [
  { src: "/screenshots/office-map-satellite.jpg", title: "RoofSpan Office · Satellite Territory Map", desc: "Every property in your market on one satellite map — clustered so whole territories read at a glance.", alt: "RoofSpan Office satellite map showing 8,029 properties clustered across a territory for roofing canvass planning", w: 1919, h: 1033 },
  { src: "/screenshots/office-map-pins.jpg", title: "RoofSpan Office · Property Pins", desc: "Zoom to street level — each home color-coded owned, rented or unknown for precise door-to-door planning.", alt: "RoofSpan Office satellite view with individual owned, rented and unknown property pins across neighborhood streets", w: 1919, h: 1033 },
  { src: "/screenshots/office-property-detail.jpg", title: "RoofSpan Office · Property Detail", desc: "Open any property for owner details, visit history and field photos — then convert it to a lead in one click.", alt: "RoofSpan Office property detail panel with owner info, record-a-visit, field photos and convert-to-lead", w: 1919, h: 1032 },
  { src: "/screenshots/office-jobs.png", title: "RoofSpan Office · Jobs", desc: "Track every job's number, scope, status and value from sold to closed out.", alt: "RoofSpan Office jobs list with job numbers, scope, status and value", w: 1600, h: 1000 },
  { src: "/screenshots/office-dashboard.png", title: "RoofSpan Office · Dashboard", desc: "A live command center: active users, recent field activity and inventory at a glance.", alt: "RoofSpan Office dashboard with active users, recent activity, and inventory metrics", w: 1600, h: 1000 },
];
const FIELD = [
  { src: "/screenshots/mobile-area.png", title: "RoofSpan Field · My Area", desc: "Each rep's assigned canvass section with property pins — their day, mapped.", alt: "RoofSpan Mobile My Area — a salesperson's assigned canvass section with property pins", w: 800, h: 1720 },
  { src: "/screenshots/mobile-leads.png", title: "RoofSpan Field · Leads", desc: "Leads created from properties in the field, synced straight back to the office.", alt: "RoofSpan Mobile field app leads created from properties", w: 800, h: 1720 },
  { src: "/screenshots/mobile-jobs.png", title: "RoofSpan Field · Jobs", desc: "The rep's job list, always current — even offline.", alt: "RoofSpan Mobile field app jobs list", w: 800, h: 1720 },
  { src: "/screenshots/mobile-home.png", title: "RoofSpan Field · My Day", desc: "A salesperson's home screen: today's route, doors and tasks.", alt: "RoofSpan Mobile field app My Day home screen", w: 800, h: 1720 },
];
const ALL = [...OFFICE, ...FIELD];

export default function Gallery() {
  const [open, setOpen] = useState(null); // index into ALL, or null

  const close = useCallback(() => setOpen(null), []);
  const step = useCallback((d) => setOpen((i) => (i === null ? i : (i + d + ALL.length) % ALL.length)), []);

  useEffect(() => {
    if (open === null) return;
    const onKey = (e) => {
      if (e.key === "Escape") close();
      else if (e.key === "ArrowRight") step(1);
      else if (e.key === "ArrowLeft") step(-1);
    };
    window.addEventListener("keydown", onKey);
    document.body.style.overflow = "hidden";
    return () => { window.removeEventListener("keydown", onKey); document.body.style.overflow = ""; };
  }, [open, close, step]);

  const active = open === null ? null : ALL[open];

  return (
    <section id="tour" className="bg-slate-soft py-20" aria-labelledby="tour-h">
      <div className="container-x">
        <SectionHeading id="tour-h" eyebrow="Product tour" title="See RoofSpan in action" sub="Real screens from RoofSpan Office and the RoofSpan Field app. Click any screen to open a closer view." />

        {/* Office */}
        <p className="mt-10 text-sm font-bold uppercase tracking-widest text-brand">RoofSpan Office</p>
        <div className="mt-4 grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {OFFICE.map((s) => (
            <BrowserCard key={s.src} shot={s} onOpen={() => setOpen(ALL.indexOf(s))} />
          ))}
        </div>

        {/* Field */}
        <p className="mt-14 text-sm font-bold uppercase tracking-widest text-brand">RoofSpan Field · Mobile</p>
        <div className="mt-4 flex flex-wrap justify-center gap-6 sm:justify-start">
          {FIELD.map((s) => (
            <PhoneCard key={s.src} shot={s} onOpen={() => setOpen(ALL.indexOf(s))} />
          ))}
        </div>
      </div>

      {active && (
        <div
          className="fixed inset-0 z-50 flex items-center justify-center bg-navy/90 p-4 backdrop-blur-sm sm:p-8"
          role="dialog" aria-modal="true" aria-label={active.title}
          data-testid="lightbox" onClick={close}
        >
          <button type="button" onClick={close} aria-label="Close" data-testid="lightbox-close"
            className="absolute right-4 top-4 inline-flex h-11 w-11 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20">
            <X className="h-5 w-5" aria-hidden="true" />
          </button>
          <button type="button" onClick={(e) => { e.stopPropagation(); step(-1); }} aria-label="Previous" data-testid="lightbox-prev"
            className="absolute left-3 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 sm:left-6">
            <ChevronLeft className="h-6 w-6" aria-hidden="true" />
          </button>
          <button type="button" onClick={(e) => { e.stopPropagation(); step(1); }} aria-label="Next" data-testid="lightbox-next"
            className="absolute right-3 top-1/2 inline-flex h-12 w-12 -translate-y-1/2 items-center justify-center rounded-full bg-white/10 text-white transition-colors hover:bg-white/20 sm:right-6">
            <ChevronRight className="h-6 w-6" aria-hidden="true" />
          </button>
          <figure className="flex max-h-full max-w-5xl flex-col items-center" onClick={(e) => e.stopPropagation()}>
            <img src={active.src} alt={active.alt} width={active.w} height={active.h}
              className="max-h-[74vh] w-auto rounded-xl object-contain shadow-2xl ring-1 ring-white/10" data-testid="lightbox-image" />
            <figcaption className="mt-4 max-w-xl text-center" data-testid="lightbox-caption">
              <p className="text-sm font-semibold text-slate-100">{active.title}</p>
              {active.desc ? <p className="mt-1 text-sm text-slate-300/80">{active.desc}</p> : null}
            </figcaption>
          </figure>
        </div>
      )}
    </section>
  );
}

function BrowserCard({ shot, onOpen }) {
  return (
    <button type="button" onClick={onOpen} data-testid={`gallery-open-${slug(shot.src)}`}
      className="group card block overflow-hidden text-left ring-1 ring-slate-line/60 transition-transform duration-200 hover:-translate-y-1 hover:shadow-lg">
      <div className="flex items-center gap-2 border-b border-slate-line bg-slate-soft px-4 py-3">
        <span className="h-3 w-3 rounded-full bg-safety" />
        <span className="h-3 w-3 rounded-full bg-brand-400" />
        <span className="h-3 w-3 rounded-full bg-emerald-400" />
        <span className="ml-3 truncate text-xs font-semibold text-slate-muted">{shot.title}</span>
        <Expand className="ml-auto h-4 w-4 text-slate-muted opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
      </div>
      <div className="relative overflow-hidden">
        <img src={shot.src} alt={shot.alt} width={shot.w} height={shot.h} loading="lazy"
          className="block w-full transition-transform duration-300 group-hover:scale-[1.03]" />
      </div>
    </button>
  );
}

function PhoneCard({ shot, onOpen }) {
  return (
    <button type="button" onClick={onOpen} data-testid={`gallery-open-${slug(shot.src)}`}
      className="group relative w-40 shrink-0 rounded-[2rem] border-[6px] border-navy bg-navy shadow-card transition-transform duration-200 hover:-translate-y-1 hover:shadow-lg sm:w-44">
      <div className="absolute left-1/2 top-2 z-10 h-3.5 w-16 -translate-x-1/2 rounded-full bg-navy" aria-hidden="true" />
      <div className="overflow-hidden rounded-[1.55rem]">
        <img src={shot.src} alt={shot.alt} width={shot.w} height={shot.h} loading="lazy"
          className="block w-full transition-transform duration-300 group-hover:scale-[1.03]" />
      </div>
      <span className="pointer-events-none absolute inset-x-0 bottom-2 mx-auto w-fit rounded-full bg-navy/80 px-3 py-1 text-[11px] font-semibold text-white opacity-0 transition-opacity group-hover:opacity-100">
        {shot.title.replace("RoofSpan Field · ", "")}
      </span>
    </button>
  );
}

function slug(src) { return src.split("/").pop().replace(/\.\w+$/, ""); }
