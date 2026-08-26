import Header from "../components/Header";
import Hero from "../components/Hero";
import { Product, HowItWorks, Roles, Differentiators, ProductProof, DataSecurity, Faq } from "../components/Sections";
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
        <ProductProof />
        <Pricing />
        <DataSecurity />
        <Faq />
        <FinalCta />
      </main>
      <Footer />
    </>
  );
}
