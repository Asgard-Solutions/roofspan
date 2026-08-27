import Header from "../components/Header";
import Hero from "../components/Hero";
import { Product, MapToMaterial, Roles, Differentiators, BigThree, MobileArea, AbcSupply, DataSecurity, Faq } from "../components/Sections";
import Gallery from "../components/Gallery";
import Pricing from "../components/Pricing";
import { FinalCta, Footer } from "../components/Footer";

export default function Home() {
  return (
    <>
      <Header />
      <main id="main">
        <Hero />
        <BigThree />
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
    </>
  );
}
