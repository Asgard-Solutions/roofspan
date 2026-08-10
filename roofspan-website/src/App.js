import MarketingSite from "./components/MarketingSite";

// The public roofspan.io website is a single marketing/download page. No router, no auth,
// no Office code. Deploys independently to https://roofspan.io.
export default function App() {
  return <MarketingSite />;
}
