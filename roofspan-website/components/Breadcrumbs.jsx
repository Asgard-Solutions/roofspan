import { ChevronRight } from "lucide-react";
import { breadcrumbLd, JsonLd } from "../src/seo";

// Visible, clickable breadcrumbs + BreadcrumbList structured data. items: [{ name, path }].
export default function Breadcrumbs({ items }) {
  return (
    <nav aria-label="Breadcrumb" className="border-b border-slate-line bg-slate-soft" data-testid="breadcrumbs">
      <ol className="container-x flex flex-wrap items-center gap-1 py-3 text-sm text-slate-muted">
        {items.map((it, i) => {
          const last = i === items.length - 1;
          return (
            <li key={it.path} className="flex items-center gap-1">
              {i > 0 ? <ChevronRight className="h-4 w-4 text-slate-line" aria-hidden="true" /> : null}
              {last ? (
                <span aria-current="page" className="font-semibold text-slate-ink">{it.name}</span>
              ) : (
                <a href={it.path} className="hover:text-brand">{it.name}</a>
              )}
            </li>
          );
        })}
      </ol>
      <JsonLd data={breadcrumbLd(items)} />
    </nav>
  );
}
