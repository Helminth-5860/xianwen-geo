import { PublicationCheckWorkspace } from "@/components/publication-check-workspace";

type SubjectPublicationChecksPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function SubjectPublicationChecksPage({
  params,
}: SubjectPublicationChecksPageProps) {
  const { id } = await params;

  return <PublicationCheckWorkspace subjectId={id} />;
}
