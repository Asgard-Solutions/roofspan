import Header from "../components/Header";
import { Footer } from "../components/Footer";
import { PAGE_LABEL } from "../src/pages";

export const metadata = {
  title: "Page not found | RoofSpan",
  description: "The page you were looking for doesn't exist. Explore RoofSpan roofing operations software instead.",
  robots: { index: false, follow: true },
};

// Rendered for unknown routes. On static export this produces out/404.html, which the host serves
// with a real HTTP 404 status.
export default function NotFound() {
  const links = ["roofing-crm-software", "roofing-canvassing-software", "roofing-territory-management", "abc-supply-integration"];
  return (
    <>
      <Header />
      <main id="main" className="bg-navy noise">
        <div className="container-x flex min-h-[60vh] flex-col items-center justify-center py-24 text-center" data-testid="not-found">
          <p className="eyebrow !text-brand-400">404</p>
          <h1 className="h1 mt-3">This page took a wrong turn off the roof</h1>
          <p className="mt-5 max-w-xl text-lg text-slate-200/85">The page you're looking for doesn't exist or has moved. Head back home or jump to one of the popular pages below.</p>
          <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
            <a href="/" className="btn-primary" data-testid="notfound-home">Back to home</a>
            <a href="/resources/" className="btn-ghost" data-testid="notfound-resources">Browse resources</a>
          </div>
          <div className="mt-10 flex flex-wrap items-center justify-center gap-3">
            {links.map((l) => (
              <a key={l} href={`/${l}/`} className="rounded-full bg-white/5 px-4 py-2 text-sm font-semibold text-slate-100 ring-1 ring-white/10 hover:bg-white/10">{PAGE_LABEL[l]}</a>
            ))}
          </div>
        </div>
      </main>
      <Footer />
    </>
  );
}
