import { useState } from "react";
import { Menu, X } from "lucide-react";

export const SITE_NAV = [
  { href: "#features", label: "Features", testid: "site-nav-features" },
  { href: "#how-it-works", label: "How It Works", testid: "site-nav-how" },
  { href: "#pricing", label: "Pricing", testid: "site-nav-pricing" },
  { href: "#download", label: "Download", testid: "site-nav-download" },
  { href: "#mobile", label: "Mobile", testid: "site-nav-mobile" },
];

export function SiteHeader() {
  const [open, setOpen] = useState(false);

  return (
    <header className="sticky top-0 z-50 border-b border-slate-200 bg-white/90 backdrop-blur" data-testid="site-header">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
        <a href="#top" className="flex items-center gap-2.5" data-testid="site-logo">
          <img src="/brand/roofspan-appicon.png" alt="RoofSpan" className="h-9 w-9 rounded-md" />
          <span className="font-heading text-lg font-bold tracking-tight text-slate-900">RoofSpan</span>
        </a>

        <nav className="hidden items-center gap-7 md:flex" data-testid="site-nav">
          {SITE_NAV.map((n) => (
            <a key={n.href} href={n.href} data-testid={n.testid} className="text-sm font-semibold text-slate-600 transition-colors hover:text-slate-900">
              {n.label}
            </a>
          ))}
          <span className="rounded-full bg-orange-50 px-3 py-1 text-xs font-bold uppercase tracking-wider text-orange-600" data-testid="site-header-coming-soon">
            Coming Soon
          </span>
        </nav>

        <button className="text-slate-900 md:hidden" onClick={() => setOpen((o) => !o)} data-testid="site-mobile-menu-button" aria-label="Menu">
          {open ? <X className="h-6 w-6" /> : <Menu className="h-6 w-6" />}
        </button>
      </div>

      {open && (
        <nav className="border-t border-slate-200 bg-white px-5 py-2 md:hidden" data-testid="site-nav-mobile-panel">
          {SITE_NAV.map((n) => (
            <a key={n.href} href={n.href} onClick={() => setOpen(false)} className="block py-2.5 text-sm font-semibold text-slate-700" data-testid={`${n.testid}-mobile`}>
              {n.label}
            </a>
          ))}
        </nav>
      )}
    </header>
  );
}
