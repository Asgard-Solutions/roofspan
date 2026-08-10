import { SITE_NAV } from "../content";

export function SiteFooter() {
  const year = new Date().getFullYear();
  return (
    <footer id="footer" className="border-t border-slate-800 bg-slate-950 py-12 text-slate-300" data-testid="site-footer">
      <div className="mx-auto max-w-6xl px-5">
        <div className="flex flex-col gap-6 md:flex-row md:items-center md:justify-between">
          <div className="flex items-center gap-2.5">
            <img src="/brand/roofspan-appicon.png" alt="RoofSpan" className="h-8 w-8 rounded-md" />
            <span className="font-heading text-lg font-bold text-white">RoofSpan</span>
          </div>
          <nav className="flex flex-wrap gap-x-6 gap-y-2" data-testid="site-footer-nav">
            {SITE_NAV.map((n) => (
              <a key={n.href} href={n.href} className="text-sm text-slate-400 transition-colors hover:text-white" data-testid={`footer-${n.testid}`}>
                {n.label}
              </a>
            ))}
          </nav>
        </div>
        <div className="mt-8 border-t border-slate-800 pt-6 text-xs text-slate-500">
          © {year} RoofSpan. All rights reserved.
        </div>
      </div>
    </footer>
  );
}
