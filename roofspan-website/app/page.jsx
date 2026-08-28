import Header from "../components/Header";
import Hero from "../components/Hero";
import { Product, MapToMaterial, Roles, Differentiators, BigThree, MobileArea, AbcSupply, DataSecurity, Faq } from "../components/Sections";
import Gallery from "../components/Gallery";
import TerritoryBanner from "../components/TerritoryBanner";
import Pricing from "../components/Pricing";
import { FinalCta, Footer } from "../components/Footer";
import { FAQ } from "../src/content";
import { webPageLd, JsonLd } from "../src/seo";

export default function Home() {
  const faqLd = { "@context": "https://schema.org", "@type": "FAQPage", mainEntity: FAQ.map((f) => ({ "@type": "Question", name: f.q, acceptedAnswer: { "@type": "Answer", text: f.a } })) };
  return (
    <>
      <Header />
      <main id="main">
        <Hero />
        <BigThree />
        <TerritoryBanner />
        <MapToMaterial />
        <Product />
        <MobileArea />
        <AbcSupply />
        <Gallery />
        <Roles />
        <Differentiators />
        <Pricing />
        <DataSecurity />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
      <JsonLd data={webPageLd({ title: "Roofing CRM & Canvassing Software | RoofSpan", description: "RoofSpan is roofing operations software for contractors that connects property intelligence, territory canvassing, field sales, jobs, and ABC Supply material workflows in one system.", path: "/" })} />
      <JsonLd data={faqLd} />
    </>
  );
}
