import VideoGenerationWorkspace from "./video-generation-workspace";

type VideoGenerationPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function VideoGenerationPage({ params }: VideoGenerationPageProps) {
  const { id } = await params;
  return <VideoGenerationWorkspace key={id} subjectId={id} />;
}
