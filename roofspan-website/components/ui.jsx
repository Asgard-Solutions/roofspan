export function SectionHeading({ eyebrow, title, sub, dark = false, id }) {
  return (
    <div className="max-w-2xl">
      {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
      <h2 id={id} className={`h2 mt-3 ${dark ? "!text-white" : ""}`}>{title}</h2>
      {sub ? <p className={`mt-4 text-lg ${dark ? "text-slate-200/80" : "text-slate-body"}`}>{sub}</p> : null}
    </div>
  );
}

// Real RoofSpan Office screenshot inside a browser-chrome frame.
export function AppMock({ src = "/screenshots/office-dashboard.png", label = "RoofSpan Office · Dashboard", alt = "RoofSpan Office dashboard showing live users, recent activity, and inventory metrics", priority = false }) {
  return (
    <div className="card overflow-hidden ring-1 ring-slate-line/60" data-testid="app-screenshot">
      <div className="flex items-center gap-2 border-b border-slate-line bg-slate-soft px-4 py-3">
        <span className="h-3 w-3 rounded-full bg-safety" />
        <span className="h-3 w-3 rounded-full bg-brand-400" />
        <span className="h-3 w-3 rounded-full bg-emerald-400" />
        <span className="ml-3 truncate text-xs font-semibold text-slate-muted">{label}</span>
      </div>
      <img src={src} alt={alt} loading={priority ? "eager" : "lazy"} fetchPriority={priority ? "high" : undefined} decoding="async" className="block w-full" width={1440} height={900} />
    </div>
  );
}

// Real RoofSpan Mobile screenshot inside a phone frame.
export function PhoneMock({ src = "/screenshots/mobile-home.png", alt = "RoofSpan Mobile field app home screen" }) {
  return (
    <div className="relative w-48 shrink-0 rounded-[2.25rem] border-[6px] border-navy bg-navy shadow-card" data-testid="mobile-screenshot">
      <div className="absolute left-1/2 top-2 z-10 h-4 w-20 -translate-x-1/2 rounded-full bg-navy" aria-hidden="true" />
      <div className="overflow-hidden rounded-[1.75rem]">
        <img src={src} alt={alt} loading="lazy" className="block w-full" width={400} height={860} />
      </div>
    </div>
  );
}
