"use client";
import { useState } from "react";
import { Check } from "lucide-react";
import { PRICE_PER_SEAT, MIN_SEATS, STARTING_PRICE, seatCost, productStatus } from "../src/config";
import { INCLUSIONS } from "../src/content";
import { SectionHeading } from "./ui";

export default function Pricing() {
  const [seats, setSeats] = useState(MIN_SEATS);
  const { seats: n, monthly, atMinimum } = seatCost(seats);
  const status = productStatus();
  return (
    <section id="pricing" className="bg-white py-20" aria-labelledby="pricing-h">
      <div className="container-x">
        <SectionHeading id="pricing-h" eyebrow="Pricing" title="One plan. Transparent per-seat pricing." sub={`$${PRICE_PER_SEAT} per user / month · ${MIN_SEATS}-user minimum · from $${STARTING_PRICE}/month`} />
        <div className="mt-10 grid gap-6 lg:grid-cols-[1.1fr,1fr]">
          <div className="card p-8">
            <p className="font-display text-5xl font-extrabold text-slate-ink">${PRICE_PER_SEAT}<span className="text-lg font-semibold text-slate-muted"> / user / mo</span></p>
            <p className="mt-1 text-slate-muted">{MIN_SEATS}-user minimum — starts at ${STARTING_PRICE}/month</p>
            <ul className="mt-6 grid gap-3 sm:grid-cols-2">
              {INCLUSIONS.map((i) => (
                <li key={i} className="flex items-start gap-2 text-slate-body"><Check className="mt-0.5 h-5 w-5 shrink-0 text-brand" aria-hidden="true" />{i}</li>
              ))}
            </ul>
            <a href={status.primaryCtaHref} className="btn-primary mt-8 w-full sm:w-auto" data-testid="pricing-cta">{status.primaryCtaLabel}</a>
          </div>
          <div className="card bg-slate-soft p-8">
            <h3 className="font-display text-xl font-bold text-slate-ink">Estimate your monthly cost</h3>
            <label htmlFor="seat-input" className="mt-6 block text-sm font-semibold text-slate-body">Number of users</label>
            <div className="mt-2 flex items-center gap-4">
              <input id="seat-input" type="range" min={MIN_SEATS} max={100} value={n} onChange={(e) => setSeats(e.target.value)}
                className="h-2 w-full accent-brand" aria-describedby="seat-help" data-testid="seat-range" />
            </div>
            <div className="mt-4 flex items-center gap-3">
              <input type="number" min={MIN_SEATS} value={n} onChange={(e) => setSeats(e.target.value)}
                className="w-24 rounded-lg border border-slate-line px-3 py-2 text-lg font-semibold" aria-label="Number of users" data-testid="seat-number" />
              <span className="text-slate-muted">users</span>
            </div>
            <p id="seat-help" className="mt-2 text-sm text-slate-muted">{atMinimum ? `Billed at the ${MIN_SEATS}-user minimum.` : "\u00A0"}</p>
            <div className="mt-6 rounded-xl2 bg-white p-5 shadow-card">
              <p className="text-sm font-semibold uppercase tracking-wide text-slate-muted">Estimated monthly</p>
              <p className="font-display text-4xl font-extrabold text-brand" data-testid="seat-total">${monthly.toLocaleString()}<span className="text-base font-semibold text-slate-muted">/mo</span></p>
              <p className="mt-1 text-sm text-slate-muted">{n} users × ${PRICE_PER_SEAT}/user</p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
