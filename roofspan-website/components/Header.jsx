"use client";
import { useState } from "react";
import { Menu, X } from "lucide-react";
import { SITE_NAV, productStatus } from "../src/config";

export default function Header() {
  const [open, setOpen] = useState(false);
  const status = productStatus();
  return (
    <header className="sticky top-0 z-40 border-b border-white/10 bg-navy/95 backdrop-blur supports-[backdrop-filter]:bg-navy/80">
      <div className="container-x flex h-16 items-center justify-between">
        <a href="#main" className="flex items-center gap-2" data-testid="brand-logo" aria-label="RoofSpan home">
          <img src="/brand/favicon.png" alt="" width={32} height={32} className="h-8 w-8 rounded-md" aria-hidden="true" />
          <span className="font-display text-lg font-extrabold text-white">RoofSpan</span>
        </a>
        <nav className="hidden items-center gap-7 md:flex" aria-label="Primary">
          {SITE_NAV.map((n) => (
            <a key={n.href} href={n.href} data-testid={n.testid} className="text-sm font-semibold text-slate-200/80 hover:text-white">{n.label}</a>
          ))}
        </nav>
        <div className="hidden md:block">
          <a href={status.primaryCtaHref} className="btn-primary !min-h-[42px] !px-5 !text-sm" data-testid="header-cta">{status.primaryCtaLabel}</a>
        </div>
        <button type="button" className="inline-flex h-11 w-11 items-center justify-center rounded-lg text-white md:hidden"
          onClick={() => setOpen((v) => !v)} aria-expanded={open} aria-controls="mobile-nav" aria-label={open ? "Close menu" : "Open menu"} data-testid="mobile-menu-button">
          {open ? <X aria-hidden="true" /> : <Menu aria-hidden="true" />}
        </button>
      </div>
      <nav id="mobile-nav" aria-label="Mobile" hidden={!open} className={`${open ? "block" : "hidden"} border-t border-white/10 bg-navy md:hidden`} data-testid="mobile-nav">
        <ul className="container-x flex flex-col py-3">
          {SITE_NAV.map((n) => (
            <li key={n.href}>
              <a href={n.href} onClick={() => setOpen(false)} className="block py-3 text-base font-semibold text-slate-100">{n.label}</a>
            </li>
          ))}
          <li><a href={productStatus().primaryCtaHref} onClick={() => setOpen(false)} className="btn-primary mt-2 w-full">{productStatus().primaryCtaLabel}</a></li>
        </ul>
      </nav>
    </header>
  );
}
