import VideoScriptWorkspace from "./video-script-workspace";

type VideoScriptPageProps = Readonly<{
  params: Promise<{ id: string }>;
  searchParams: Promise<{ topic?: string | string[]; article_id?: string | string[] }>;
}>;

export default async function VideoScriptPage({ params, searchParams }: VideoScriptPageProps) {
  const { id } = await params;
  const query = await searchParams;
  const topic = Array.isArray(query.topic) ? query.topic[0] : query.topic;
  const sourceArticleId = Array.isArray(query.article_id) ? query.article_id[0] : query.article_id;
  return (
    <VideoScriptWorkspace
      subjectId={id}
      initialTopic={topic ?? ""}
      initialSourceArticleId={sourceArticleId ?? ""}
    />
  );
}
