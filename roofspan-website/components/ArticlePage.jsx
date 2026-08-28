import { ArrowRight } from "lucide-react";
import Header from "./Header";
import Breadcrumbs from "./Breadcrumbs";
import { FinalCta, Footer } from "./Footer";
import { ARTICLES } from "../src/resources";
import { PAGES, PAGE_LABEL } from "../src/pages";
import { webPageLd, articleLd, JsonLd } from "../src/seo";

// Renders a single Resources article from its definition. Server component.
export default function ArticlePage({ slug }) {
  const a = ARTICLES[slug];
  const path = `/resources/${slug}/`;
  const crumbs = [{ name: "Home", path: "/" }, { name: "Resources", path: "/resources/" }, { name: a.title, path }];

  return (
    <>
      <Header />
      <Breadcrumbs items={crumbs} />
      <main id="main">
        <article className="bg-white">
          <header className="border-b border-slate-line bg-slate-soft py-14">
            <div className="container-x max-w-3xl">
              <p className="eyebrow">Resource</p>
              <h1 className="h2 mt-3 !text-4xl sm:!text-5xl">{a.title}</h1>
              <p className="mt-4 text-lg text-slate-body">{a.dek}</p>
            </div>
          </header>
          <div className="container-x max-w-3xl py-12">
            {a.sections.map((s, i) => (
              <section key={i} className="mb-8" data-testid={`article-section-${i}`}>
                <h2 className="font-display text-2xl font-bold text-slate-ink">{s.h2}</h2>
                {s.p.map((para, j) => (
                  <p key={j} className="mt-3 text-lg leading-relaxed text-slate-body">{para}</p>
                ))}
              </section>
            ))}

            <div className="mt-10 rounded-xl2 border border-slate-line bg-slate-soft p-6" data-testid="article-related">
              <p className="font-display text-lg font-bold text-slate-ink">Related in RoofSpan</p>
              <ul className="mt-3 space-y-2">
                {(a.related || []).filter((r) => PAGES[r] || r === "roofing-software-pricing").map((r) => (
                  <li key={r}>
                    <a href={`/${r}/`} className="inline-flex items-center gap-2 font-semibold text-brand hover:underline" data-testid={`article-link-${r}`}>
                      {PAGE_LABEL[r] || r} <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    </a>
                  </li>
                ))}
              </ul>
            </div>

            <p className="mt-8"><a href="/resources/" className="font-semibold text-brand hover:underline" data-testid="back-to-resources">← All resources</a></p>
          </div>
        </article>
        <FinalCta />
      </main>
      <Footer />
      <JsonLd data={webPageLd({ title: a.title, description: a.description, path })} />
      <JsonLd data={articleLd({ title: a.title, description: a.description, path, datePublished: a.datePublished })} />
    </>
  );
}
