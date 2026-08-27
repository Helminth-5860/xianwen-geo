import { ImageGenerationWorkspace } from "@/components/image-generation-workspace";

type SubjectImagesPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function SubjectImagesPage({ params }: SubjectImagesPageProps) {
  const { id } = await params;

  return <ImageGenerationWorkspace subjectId={id} />;
}
