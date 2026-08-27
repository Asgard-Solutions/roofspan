"use client";
import { useEffect, useRef, useState } from "react";
import { Home, MapPin, CheckCircle2, Layers } from "lucide-react";

const STATS = [
  { icon: Home, value: "8,029", label: "properties mapped", accent: "text-brand-400" },
  { icon: MapPin, value: "3,652", label: "precisely located", accent: "text-safety" },
  { icon: CheckCircle2, value: "7,529", label: "doors checked", accent: "text-emerald-400" },
  { icon: Layers, value: "100%", label: "territory coverage", accent: "text-white" },
];

// Full-width "territory intelligence" banner. The clustered satellite map fills the section behind a
// navy gradient; the stat callouts fade + rise in when the banner scrolls into view (respecting
// prefers-reduced-motion via the global animation reset).
export default function TerritoryBanner() {
  const ref = useRef(null);
  const [shown, setShown] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const io = new IntersectionObserver(
      ([e]) => { if (e.isIntersecting) { setShown(true); io.disconnect(); } },
      { threshold: 0.2 }
    );
    io.observe(el);
    return () => io.disconnect();
  }, []);

  return (
    <section className="relative overflow-hidden bg-navy py-20 sm:py-28" aria-labelledby="territory-h" data-testid="territory-banner">
      <img src="/screenshots/office-map-satellite.jpg" alt="" aria-hidden="true"
        className="absolute inset-0 h-full w-full object-cover object-center opacity-30" />
      <div className="absolute inset-0 bg-gradient-to-br from-navy via-navy/90 to-navy/55" aria-hidden="true" />
      <div className="noise absolute inset-0" aria-hidden="true" />

      <div className="container-x relative">
        <p className="eyebrow !text-safety">Territory intelligence</p>
        <h2 id="territory-h" className="h2 mt-3 max-w-2xl !text-white">
          See your entire market before you knock a single door.
        </h2>
        <p className="mt-4 max-w-2xl text-lg text-slate-200/85">
          RoofSpan plots every property in your service area onto one satellite view — clustered,
          color-coded and canvass-ready — so your team targets the right streets first instead of
          guessing block by block.
        </p>

        <div ref={ref} className="mt-12 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {STATS.map((s, i) => {
            const Icon = s.icon;
            return (
              <div
                key={s.label}
                data-testid={`territory-stat-${i}`}
                className={`rounded-xl2 border border-white/10 bg-white/5 p-6 backdrop-blur-sm transition-all duration-700 ease-out ${shown ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0"}`}
                style={{ transitionDelay: `${i * 120}ms` }}
              >
                <Icon className={`h-7 w-7 ${s.accent}`} aria-hidden="true" />
                <p className="mt-4 font-display text-4xl font-extrabold tracking-tight text-white">{s.value}</p>
                <p className="mt-1 text-sm font-semibold text-slate-200/75">{s.label}</p>
              </div>
            );
          })}
        </div>
      </div>
    </section>
  );
}
