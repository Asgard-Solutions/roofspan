import Header from "../../components/Header";
import Breadcrumbs from "../../components/Breadcrumbs";
import { FinalCta, Footer } from "../../components/Footer";
import { pageMeta, webPageLd, JsonLd } from "../../src/seo";
import { STARTING_PRICE } from "../../src/config";

const TITLE = "About RoofSpan | Roofing Operations Software";
const DESC = "About RoofSpan — roofing operations software that connects property intelligence, canvassing, field sales, jobs, and ABC Supply purchasing, running on your company's own Windows system.";
const PATH = "/about/";

export const metadata = pageMeta({ title: TITLE, description: DESC, path: PATH });

export default function Page() {
  const crumbs = [{ name: "Home", path: "/" }, { name: "About", path: PATH }];
  return (
    <>
      <Header />
      <Breadcrumbs items={crumbs} />
      <main id="main">
        <section className="noise bg-navy py-16" aria-labelledby="about-h1">
          <div className="container-x max-w-3xl">
            <p className="eyebrow !text-brand-400">About</p>
            <h1 id="about-h1" className="h1 mt-3">Roofing software built around the whole operation</h1>
            <p className="mt-5 text-lg text-slate-200/85">RoofSpan is roofing operations software for contractors. It connects the parts of a roofing business that usually live in separate tools — property intelligence, territory canvassing, field sales, leads, inspections, quotes, jobs, and ABC Supply material purchasing — into one connected system.</p>
          </div>
        </section>
        <section className="bg-white py-14">
          <div className="container-x max-w-3xl space-y-8">
            <div>
              <h2 className="font-display text-2xl font-bold text-slate-ink">What RoofSpan is</h2>
              <p className="mt-3 text-lg text-slate-body">RoofSpan has two parts. RoofSpan Office installs and runs on your company's own Windows machine and opens through a local browser interface. RoofSpan Mobile is a free companion app that field crews and salespeople pair with your Office installation so they can work from the same records while away from the office.</p>
            </div>
            <div>
              <h2 className="font-display text-2xl font-bold text-slate-ink">Why it's different</h2>
              <p className="mt-3 text-lg text-slate-body">Most roofing tools start at the lead. RoofSpan starts at the property — on the map — and carries the work all the way through to materials. Because the office and field share one set of records, activity in the field becomes a pipeline the office can actually manage.</p>
            </div>
            <div>
              <h2 className="font-display text-2xl font-bold text-slate-ink">Your data, your system</h2>
              <p className="mt-3 text-lg text-slate-body">Your operational roofing database lives with your own RoofSpan Office installation. Pricing is transparent — one plan, one per-seat price, a five-user minimum, from ${STARTING_PRICE}/month — with the RoofSpan Mobile companion apps included.</p>
            </div>
            <p className="text-lg text-slate-body">RoofSpan is currently in early access. <a href="/contact/" className="font-semibold text-brand hover:underline">Get in touch</a> to get set up or book a walkthrough.</p>
          </div>
        </section>
        <FinalCta />
      </main>
      <Footer />
      <JsonLd data={webPageLd({ title: TITLE, description: DESC, path: PATH })} />
    </>
  );
}
