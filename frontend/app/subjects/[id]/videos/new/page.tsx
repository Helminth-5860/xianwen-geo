import { redirect } from "next/navigation";

type VideoGenerationPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function VideoGenerationPage({ params }: VideoGenerationPageProps) {
  const { id } = await params;
  redirect(`/subjects/${id}/video-library`);
}
