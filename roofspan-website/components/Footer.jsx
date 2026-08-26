import { CONTACT_EMAIL, STARTING_PRICE } from "../src/config";
import EarlyAccessForm from "./EarlyAccessForm";

export function FinalCta() {
  return (
    <section id="early-access" className="bg-navy py-20 noise" aria-labelledby="cta-h">
      <div className="container-x grid items-start gap-12 lg:grid-cols-2">
        <div>
          <h2 id="cta-h" className="h2 !text-white">Ready to run your roofing operation on RoofSpan?</h2>
          <p className="mt-4 text-lg text-slate-200/85">RoofSpan is in early access. Join the list to get set up, or book a walkthrough with our team — same form, we'll route it either way.</p>
          <p className="mt-6 text-slate-200/80">Prefer email? Reach us at <a href={`mailto:${CONTACT_EMAIL}`} className="font-semibold text-white underline underline-offset-4" data-testid="contact-email-cta">{CONTACT_EMAIL}</a>.</p>
          <p className="mt-2 text-sm text-slate-300/70">Transparent pricing from ${STARTING_PRICE}/month · runs on your own Windows system.</p>
        </div>
        <EarlyAccessForm />
      </div>
    </section>
  );
}

export function Footer() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-white/10 bg-navy-900 py-12 text-slate-300" aria-label="Footer">
      <div className="container-x grid gap-8 sm:grid-cols-2 lg:grid-cols-4">
        <div>
          <div className="flex items-center gap-2">
            <img src="/brand/favicon.png" alt="" width={28} height={28} className="h-7 w-7 rounded-md" aria-hidden="true" />
            <span className="font-display text-lg font-extrabold text-white">RoofSpan</span>
          </div>
          <p className="mt-3 max-w-xs text-sm text-slate-400">Roofing operations software that connects your office and field crews on your own Windows system.</p>
        </div>
        <nav aria-label="Product">
          <p className="text-sm font-bold uppercase tracking-wide text-slate-500">Product</p>
          <ul className="mt-3 space-y-2 text-sm">
            <li><a href="#product" className="hover:text-white">Product</a></li>
            <li><a href="#how-it-works" className="hover:text-white">How it works</a></li>
            <li><a href="#pricing" className="hover:text-white">Pricing</a></li>
            <li><a href="#data" className="hover:text-white">Security & data</a></li>
          </ul>
        </nav>
        <nav aria-label="Company">
          <p className="text-sm font-bold uppercase tracking-wide text-slate-500">Get started</p>
          <ul className="mt-3 space-y-2 text-sm">
            <li><a href="#early-access" className="hover:text-white">Join early access</a></li>
            <li><a href={`mailto:${CONTACT_EMAIL}`} className="hover:text-white" data-testid="footer-contact">{CONTACT_EMAIL}</a></li>
          </ul>
        </nav>
        <div>
          <p className="text-sm font-bold uppercase tracking-wide text-slate-500">Availability</p>
          <p className="mt-3 text-sm text-slate-400">RoofSpan Office for Windows · free RoofSpan Mobile companion. Early access now.</p>
        </div>
      </div>
      <div className="container-x mt-10 border-t border-white/10 pt-6 text-sm text-slate-500">
        © {year} RoofSpan. All rights reserved.
      </div>
    </footer>
  );
}
