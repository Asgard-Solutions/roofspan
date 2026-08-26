import { ClipboardList, Camera, MapPin, Hammer, Boxes, Users2 } from "lucide-react";

export function SectionHeading({ eyebrow, title, sub, dark = false, id }) {
  return (
    <div className="max-w-2xl">
      {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
      <h2 id={id} className={`h2 mt-3 ${dark ? "!text-white" : ""}`}>{title}</h2>
      {sub ? <p className={`mt-4 text-lg ${dark ? "text-slate-200/80" : "text-slate-body"}`}>{sub}</p> : null}
    </div>
  );
}

// In-code representation of the RoofSpan Office interface. Uses OBVIOUSLY FICTIONAL example data and
// no invented metrics. Structured so a real redacted screenshot can replace it without page redesign.
export function AppMock() {
  const jobs = [
    { id: "JOB-1042", name: "Alderman Residence", city: "Springfield · Example St", status: "Inspection" },
    { id: "JOB-1043", name: "Ridgeline Warehouse", city: "Example City · Depot Rd", status: "Estimate" },
    { id: "JOB-1044", name: "Maple Court HOA", city: "Sample Town · Maple Ct", status: "Scheduled" },
  ];
  return (
    <div className="card overflow-hidden" role="img" aria-label="Example RoofSpan Office job list with fictional sample data">
      <div className="flex items-center gap-2 border-b border-slate-line bg-slate-soft px-4 py-3">
        <span className="h-3 w-3 rounded-full bg-safety" />
        <span className="h-3 w-3 rounded-full bg-brand-400" />
        <span className="h-3 w-3 rounded-full bg-slate-line" />
        <span className="ml-3 text-xs font-semibold text-slate-muted">RoofSpan Office · Jobs</span>
      </div>
      <div className="grid grid-cols-3 gap-2 p-4 text-center">
        {[["Leads", ClipboardList], ["Inspections", Camera], ["Properties", MapPin]].map(([l, Icon]) => (
          <div key={l} className="rounded-lg bg-slate-soft py-3">
            <Icon className="mx-auto h-5 w-5 text-brand" aria-hidden="true" />
            <p className="mt-1 text-xs font-semibold text-slate-ink">{l}</p>
          </div>
        ))}
      </div>
      <ul className="divide-y divide-slate-line px-4 pb-4">
        {jobs.map((j) => (
          <li key={j.id} className="flex items-center justify-between py-3">
            <div className="text-left">
              <p className="text-sm font-semibold text-slate-ink">{j.name}</p>
              <p className="text-xs text-slate-muted">{j.id} · {j.city}</p>
            </div>
            <span className="rounded-full bg-brand/10 px-3 py-1 text-xs font-bold text-brand">{j.status}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function PhoneMock() {
  return (
    <div className="card w-44 shrink-0 overflow-hidden rounded-[1.75rem] border-4 border-navy" role="img" aria-label="Example RoofSpan Mobile screen with fictional sample data">
      <div className="bg-navy px-3 py-2 text-center text-[10px] font-bold text-white">RoofSpan Mobile</div>
      <div className="space-y-2 p-3">
        {[["Alderman Residence", Camera], ["Ridgeline Warehouse", Hammer], ["Maple Court HOA", Boxes], ["New lead — Example Ave", Users2]].map(([t, Icon]) => (
          <div key={t} className="flex items-center gap-2 rounded-lg bg-slate-soft px-2 py-2">
            <Icon className="h-4 w-4 text-brand" aria-hidden="true" />
            <span className="text-[11px] font-medium text-slate-ink">{t}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
