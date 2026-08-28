import Header from "../../components/Header";
import Breadcrumbs from "../../components/Breadcrumbs";
import EarlyAccessForm from "../../components/EarlyAccessForm";
import { Footer } from "../../components/Footer";
import { pageMeta, webPageLd, JsonLd } from "../../src/seo";
import { CONTACT_EMAIL } from "../../src/config";

const TITLE = "Contact RoofSpan";
const DESC = "Contact RoofSpan to get set up on roofing operations software or book a walkthrough. Reach the team by email or the early-access form.";
const PATH = "/contact/";

export const metadata = pageMeta({ title: TITLE, description: DESC, path: PATH });

export default function Page() {
  const crumbs = [{ name: "Home", path: "/" }, { name: "Contact", path: PATH }];
  return (
    <>
      <Header />
      <Breadcrumbs items={crumbs} />
      <main id="main">
        <section className="bg-navy py-16 noise" aria-labelledby="contact-h1">
          <div className="container-x grid items-start gap-12 lg:grid-cols-2">
            <div>
              <p className="eyebrow !text-brand-400">Contact</p>
              <h1 id="contact-h1" className="h1 mt-3">Talk to RoofSpan</h1>
              <p className="mt-5 text-lg text-slate-200/85">RoofSpan is in early access. Tell us about your roofing company and we'll help you get set up, or book a walkthrough with our team — the same form routes either way.</p>
              <p className="mt-6 text-slate-200/85">Prefer email? Reach us at <a href={`mailto:${CONTACT_EMAIL}`} className="font-semibold text-white underline underline-offset-4" data-testid="contact-email">{CONTACT_EMAIL}</a>.</p>
            </div>
            <EarlyAccessForm />
          </div>
        </section>
      </main>
      <Footer />
      <JsonLd data={webPageLd({ title: TITLE, description: DESC, path: PATH })} />
    </>
  );
}
