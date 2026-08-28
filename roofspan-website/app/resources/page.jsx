import Header from "../../components/Header";
import Breadcrumbs from "../../components/Breadcrumbs";
import { FinalCta, Footer } from "../../components/Footer";
import CtaButton from "../../components/CtaButton";
import { ARTICLES } from "../../src/resources";
import { pageMeta, webPageLd, JsonLd } from "../../src/seo";
import { ArrowRight } from "lucide-react";

const TITLE = "Roofing Software Resources & Guides | RoofSpan";
const DESC = "Buyer's guides and how-tos for roofing contractors — choosing roofing CRM and canvassing software, organizing sales territories, managing leads, and ABC Supply integration.";
const PATH = "/resources/";

export const metadata = pageMeta({ title: TITLE, description: DESC, path: PATH });

export default function Page() {
  const crumbs = [{ name: "Home", path: "/" }, { name: "Resources", path: PATH }];
  const entries = Object.entries(ARTICLES);
  const itemListLd = {
    "@context": "https://schema.org", "@type": "ItemList",
    itemListElement: entries.map(([slug, a], i) => ({ "@type": "ListItem", position: i + 1, name: a.title, url: `${PATH}${slug}/` })),
  };
  return (
    <>
      <Header />
      <Breadcrumbs items={crumbs} />
      <main id="main">
        <section className="bg-navy py-16 noise" aria-labelledby="resources-h1">
          <div className="container-x max-w-3xl">
            <p className="eyebrow !text-brand-400">Resources</p>
            <h1 id="resources-h1" className="h1 mt-3">Roofing software guides & resources</h1>
            <p className="mt-5 text-lg text-slate-200/85">Practical, no-fluff guides for roofing contractors evaluating software — from CRM and canvassing to territories, leads, jobs, and ABC Supply purchasing.</p>
          </div>
        </section>
        <section className="bg-slate-soft py-14" aria-label="Articles">
          <div className="container-x grid gap-6 md:grid-cols-2 lg:grid-cols-3">
            {entries.map(([slug, a]) => (
              <CtaButton key={slug} href={`/resources/${slug}/`} event="resource_click" params={{ resource: slug }} className="card flex flex-col p-6 text-left transition-transform hover:-translate-y-1" testid={`resource-${slug}`}>
                <h2 className="font-display text-lg font-bold text-slate-ink">{a.title}</h2>
                <p className="mt-2 flex-1 text-slate-body">{a.dek}</p>
                <span className="mt-4 inline-flex items-center gap-2 font-semibold text-brand">Read guide <ArrowRight className="h-4 w-4" aria-hidden="true" /></span>
              </CtaButton>
            ))}
          </div>
        </section>
        <FinalCta />
      </main>
      <Footer />
      <JsonLd data={webPageLd({ title: TITLE, description: DESC, path: PATH })} />
      <JsonLd data={itemListLd} />
    </>
  );
}
