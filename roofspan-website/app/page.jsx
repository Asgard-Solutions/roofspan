import Header from "../components/Header";
import Hero from "../components/Hero";
import { Product, HowItWorks, Roles, Differentiators, DataSecurity, Faq } from "../components/Sections";
import Gallery from "../components/Gallery";
import Pricing from "../components/Pricing";
import { FinalCta, Footer } from "../components/Footer";

export default function Home() {
  return (
    <>
      <Header />
      <main id="main">
        <Hero />
        <Product />
        <HowItWorks />
        <Roles />
        <Differentiators />
        <Gallery />
        <Pricing />
        <DataSecurity />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
