import { Check, ArrowRight } from "lucide-react";
import Header from "./Header";
import Breadcrumbs from "./Breadcrumbs";
import CtaButton from "./CtaButton";
import { AppMock, PhoneMock } from "./ui";
import { FinalCta, Footer } from "./Footer";
import { PAGES, PAGE_LABEL } from "../src/pages";
import { webPageLd, JsonLd } from "../src/seo";

// Renders a dedicated commercial SEO page from its content definition. Server component.
export default function CommercialPage({ slug }) {
  const p = PAGES[slug];
  const path = `/${slug}/`;
  const crumbs = [{ name: "Home", path: "/" }, { name: p.nav, path }];
  const faqLd = p.faq
    ? { "@context": "https://schema.org", "@type": "FAQPage", mainEntity: p.faq.map((f) => ({ "@type": "Question", name: f.q, acceptedAnswer: { "@type": "Answer", text: f.a } })) }
    : null;

  return (
    <>
      <Header />
      <Breadcrumbs items={crumbs} />
      <main id="main">
        {/* Hero */}
        <section className="noise relative overflow-hidden bg-navy" aria-labelledby="page-h1">
          <div className="pointer-events-none absolute -right-40 -top-40 h-[520px] w-[520px] rounded-full bg-brand/20 blur-3xl" aria-hidden="true" />
          <div className="container-x relative grid items-center gap-12 py-16 lg:grid-cols-[1.05fr,1fr] lg:py-20">
            <div>
              <p className="eyebrow !text-brand-400">{p.eyebrow}</p>
              <h1 id="page-h1" className="h1 mt-3">{p.h1}</h1>
              <p className="mt-5 max-w-xl text-lg text-slate-200/85">{p.intro}</p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <CtaButton href="/#early-access" label={`${p.nav} — Join Early Access`} params={{ page: slug }} testid="page-primary-cta">
                  Join Early Access <ArrowRight className="h-4 w-4" aria-hidden="true" />
                </CtaButton>
                <CtaButton href="/#tour" label="See the product tour" event="product_tour_click" className="btn-ghost" testid="page-secondary-cta">
                  See the product tour
                </CtaButton>
              </div>
            </div>
            <div className="flex items-center justify-center">
              {p.screenshot?.phone
                ? <PhoneMock src={p.screenshot.src} alt={p.screenshot.alt} />
                : <div className="w-full max-w-md"><AppMock src={p.screenshot.src} label={p.screenshot.label} alt={p.screenshot.alt} priority /></div>}
            </div>
          </div>
        </section>

        {/* Feature sections */}
        <section className="bg-white py-16" aria-label={`${p.nav} details`}>
          <div className="container-x space-y-12">
            {p.sections.map((s, i) => (
              <div key={i} className="grid gap-6 lg:grid-cols-[1fr,1.2fr]" data-testid={`page-section-${i}`}>
                <h2 className="h2">{s.title}</h2>
                <div>
                  <p className="text-lg text-slate-body">{s.body}</p>
                  {s.bullets ? (
                    <ul className="mt-5 grid gap-3 sm:grid-cols-2">
                      {s.bullets.map((b) => (
                        <li key={b} className="flex items-start gap-2 text-slate-body"><Check className="mt-0.5 h-5 w-5 shrink-0 text-brand" aria-hidden="true" />{b}</li>
                      ))}
                    </ul>
                  ) : null}
                </div>
              </div>
            ))}
            {p.note ? <p className="max-w-3xl text-sm text-slate-muted" data-testid="page-note">{p.note}</p> : null}
          </div>
        </section>

        {/* FAQ (if present) */}
        {p.faq ? (
          <section className="bg-slate-soft py-16" aria-labelledby="page-faq-h">
            <div className="container-x max-w-3xl">
              <h2 id="page-faq-h" className="h2">Common questions</h2>
              <div className="mt-6 divide-y divide-slate-line">
                {p.faq.map((f, i) => (
                  <details key={i} className="group py-4" data-testid={`page-faq-${i}`}>
                    <summary className="cursor-pointer list-none font-display text-lg font-semibold text-slate-ink [&::-webkit-details-marker]:hidden">{f.q}</summary>
                    <p className="mt-3 text-slate-body">{f.a}</p>
                  </details>
                ))}
              </div>
            </div>
          </section>
        ) : null}

        {/* Related links */}
        <section className="bg-white py-16" aria-labelledby="related-h">
          <div className="container-x">
            <h2 id="related-h" className="h2">Explore more of RoofSpan</h2>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {(p.related || []).map((r) => (
                <a key={r} href={`/${r}/`} className="card flex items-center justify-between p-5 transition-transform hover:-translate-y-0.5" data-testid={`related-${r}`}>
                  <span className="font-display font-bold text-slate-ink">{PAGE_LABEL[r] || r}</span>
                  <ArrowRight className="h-5 w-5 text-brand" aria-hidden="true" />
                </a>
              ))}
            </div>
          </div>
        </section>

        <FinalCta />
      </main>
      <Footer />
      <JsonLd data={webPageLd({ title: p.title, description: p.description, path })} />
      {faqLd ? <JsonLd data={faqLd} /> : null}
    </>
  );
}
