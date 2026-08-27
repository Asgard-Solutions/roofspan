import "./globals.css";
import { Manrope, IBM_Plex_Sans } from "next/font/google";
import { SITE_URL, CONTACT_EMAIL, STARTING_PRICE, PRICE_PER_SEAT, MIN_SEATS } from "../src/config";
import { FAQ } from "../src/content";

// Self-hosted at build time by next/font (no runtime Google Fonts request, no duplicates).
const manrope = Manrope({ subsets: ["latin"], weight: ["600", "700", "800"], variable: "--font-manrope", display: "swap" });
const ibm = IBM_Plex_Sans({ subsets: ["latin"], weight: ["400", "500", "600", "700"], variable: "--font-ibm", display: "swap" });

const title = "RoofSpan — Roofing CRM, Canvassing & Operations Software";
const description = "RoofSpan connects property intelligence, roofing canvassing and territory management, field sales, jobs, and ABC Supply purchasing in one roofing operations platform that runs on your company's own Windows system.";
const keywords = [
  "roofing operations software", "roofing CRM", "roofing canvassing software",
  "roofing territory management", "roofing sales mapping", "property intelligence for roofing contractors",
  "roofing field sales software", "ABC Supply integration", "roofing material purchasing software",
  "roofing mobile field app",
];

export const metadata = {
  metadataBase: new URL(SITE_URL),
  title,
  description,
  keywords,
  alternates: { canonical: "/" },
  icons: { icon: "/brand/favicon.png", apple: "/brand/apple-touch-icon.png" },
  openGraph: { type: "website", url: SITE_URL, siteName: "RoofSpan", title, description, images: [{ url: "/brand/og.png", width: 1200, height: 630, alt: "RoofSpan roofing operations software" }] },
  twitter: { card: "summary_large_image", title, description, images: ["/brand/og.png"] },
  robots: { index: true, follow: true },
};

export const viewport = { themeColor: "#0B1B3A" };

function JsonLd() {
  const org = { "@context": "https://schema.org", "@type": "Organization", name: "RoofSpan", url: SITE_URL, email: CONTACT_EMAIL, logo: `${SITE_URL}/brand/favicon.png` };
  const app = {
    "@context": "https://schema.org", "@type": "SoftwareApplication", name: "RoofSpan Office",
    applicationCategory: "BusinessApplication", operatingSystem: "Windows",
    description, url: SITE_URL,
    featureList: [
      "Property intelligence and mapping",
      "Roofing sales territory and canvass planning",
      "Salesperson My Area field workflow",
      "Offline-capable RoofSpan Mobile field app",
      "Lead, inspection, quote and job workflow",
      "ABC Supply catalog, account pricing, ordering and order history",
      "Inventory and purchase order management",
      "Locally controlled RoofSpan Office data (Windows)",
    ],
    offers: { "@type": "Offer", price: String(PRICE_PER_SEAT), priceCurrency: "USD", description: `$${PRICE_PER_SEAT} per user/month, ${MIN_SEATS}-user minimum (from $${STARTING_PRICE}/month)` },
  };
  const faq = { "@context": "https://schema.org", "@type": "FAQPage", mainEntity: FAQ.map((f) => ({ "@type": "Question", name: f.q, acceptedAnswer: { "@type": "Answer", text: f.a } })) };
  return (
    <>
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(org) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(app) }} />
      <script type="application/ld+json" dangerouslySetInnerHTML={{ __html: JSON.stringify(faq) }} />
    </>
  );
}

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${manrope.variable} ${ibm.variable}`}>
      <body>
        <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:z-50 focus:left-4 focus:top-4 focus:rounded-lg focus:bg-navy focus:px-4 focus:py-2 focus:text-white" data-testid="skip-to-content">Skip to content</a>
        {children}
        <JsonLd />
      </body>
    </html>
  );
}
