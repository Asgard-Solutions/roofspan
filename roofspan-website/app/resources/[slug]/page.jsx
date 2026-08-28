import ArticlePage from "../../../components/ArticlePage";
import { ARTICLES, ARTICLE_SLUGS } from "../../../src/resources";
import { pageMeta } from "../../../src/seo";

export function generateStaticParams() {
  return ARTICLE_SLUGS.map((slug) => ({ slug }));
}

export function generateMetadata({ params }) {
  const a = ARTICLES[params.slug];
  if (!a) return {};
  return pageMeta({ title: `${a.title} | RoofSpan`, description: a.description, path: `/resources/${params.slug}/` });
}

export default function Page({ params }) {
  return <ArticlePage slug={params.slug} />;
}
