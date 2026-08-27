import { CustomLibraryWorkspace } from "@/components/custom-library-workspace";

type SubjectCustomLibraryPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function SubjectCustomLibraryPage({ params }: SubjectCustomLibraryPageProps) {
  const { id } = await params;

  return <CustomLibraryWorkspace subjectId={id} />;
}
