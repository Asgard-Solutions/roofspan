import CommercialPage from "../../components/CommercialPage";
import { PAGES } from "../../src/pages";
import { pageMeta } from "../../src/seo";

const SLUG = "abc-supply-integration";
export const metadata = pageMeta({ title: PAGES[SLUG].title, description: PAGES[SLUG].description, path: `/${SLUG}/` });
export default function Page() { return <CommercialPage slug={SLUG} />; }
