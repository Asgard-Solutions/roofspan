import Header from "../../components/Header";
import Breadcrumbs from "../../components/Breadcrumbs";
import Pricing from "../../components/Pricing";
import { FinalCta, Footer } from "../../components/Footer";
import { PAGE_LABEL } from "../../src/pages";
import { pageMeta, webPageLd, JsonLd } from "../../src/seo";
import { STARTING_PRICE, PRICE_PER_SEAT, MIN_SEATS } from "../../src/config";
import { ArrowRight } from "lucide-react";

const SLUG = "roofing-software-pricing";
const TITLE = "Roofing Software Pricing | RoofSpan";
const DESC = `RoofSpan roofing software pricing: $${PRICE_PER_SEAT} per user per month with a ${MIN_SEATS}-user minimum (from $${STARTING_PRICE}/month). One plan, free RoofSpan Mobile included.`;
const PATH = `/${SLUG}/`;

export const metadata = pageMeta({ title: TITLE, description: DESC, path: PATH });

export default function Page() {
  const crumbs = [{ name: "Home", path: "/" }, { name: "Pricing", path: PATH }];
  return (
    <>
      <Header />
      <Breadcrumbs items={crumbs} />
      <main id="main">
        <section className="noise bg-navy py-16" aria-labelledby="pricing-page-h1">
          <div className="container-x max-w-3xl">
            <p className="eyebrow !text-brand-400">Pricing</p>
            <h1 id="pricing-page-h1" className="h1 mt-3">Transparent roofing software pricing</h1>
            <p className="mt-5 text-lg text-slate-200/85">One plan, one per-seat price, and a clear five-user minimum. RoofSpan Office runs on your own Windows system and the RoofSpan Mobile companion apps are included at no extra cost.</p>
          </div>
        </section>
        <Pricing />
        <section className="bg-slate-soft py-14" aria-labelledby="pricing-explore-h">
          <div className="container-x">
            <h2 id="pricing-explore-h" className="h2">What's included</h2>
            <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {["roofing-crm-software", "roofing-canvassing-software", "roofing-territory-management", "roofing-field-sales-software", "abc-supply-integration", "roofing-job-management-software"].map((r) => (
                <a key={r} href={`/${r}/`} className="card flex items-center justify-between p-5 transition-transform hover:-translate-y-0.5" data-testid={`pricing-related-${r}`}>
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
      <JsonLd data={webPageLd({ title: TITLE, description: DESC, path: PATH })} />
    </>
  );
}
