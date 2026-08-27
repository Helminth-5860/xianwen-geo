import { SubjectImageLibraryWorkspace } from "@/components/subject-image-library-workspace";

type SubjectImageLibraryPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function SubjectImageLibraryPage({ params }: SubjectImageLibraryPageProps) {
  const { id } = await params;

  return <SubjectImageLibraryWorkspace subjectId={id} />;
}
