import ArticleWorkspace from "./article-workspace";

type ArticlePageProps = Readonly<{
  params: Promise<{ id: string }>;
  searchParams: Promise<{ topic?: string | string[] }>;
}>;

export default async function ArticlePage({ params, searchParams }: ArticlePageProps) {
  const { id } = await params;
  const query = await searchParams;
  const topic = Array.isArray(query.topic) ? query.topic[0] : query.topic;
  return <ArticleWorkspace subjectId={id} initialTopic={topic ?? ""} />;
}
