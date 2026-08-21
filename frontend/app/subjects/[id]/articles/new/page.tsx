type ArticleIntentPageProps = Readonly<{
  params: Promise<{ id: string }>;
  searchParams: Promise<{ topic?: string | string[] }>;
}>;

export default async function ArticleIntentPage({ params, searchParams }: ArticleIntentPageProps) {
  const { id } = await params;
  const query = await searchParams;
  const topic = Array.isArray(query.topic) ? query.topic[0] : query.topic;

  return (
    <main className="page-shell">
      <h1>文章主题意图</h1>
      <p>主体：{id}</p>
      <p>推荐主题：{topic || "未指定"}</p>
      <p>
        当前页面只接收策略推荐的主题，不会自动生成文章，也不会扣除文章额度。完整文章生成属于 Stage
        2。
      </p>
      <a href={`/subjects/${id}`}>返回主体</a>
    </main>
  );
}
