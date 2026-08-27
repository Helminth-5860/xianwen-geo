import { VideoLibraryWorkspace } from "@/components/video-library-workspace";

type SubjectVideoLibraryPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function SubjectVideoLibraryPage({ params }: SubjectVideoLibraryPageProps) {
  const { id } = await params;

  return <VideoLibraryWorkspace subjectId={id} />;
}
