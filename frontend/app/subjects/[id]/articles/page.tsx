import ContentLibrary from "./content-library";

type ContentLibraryPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function ContentLibraryPage({ params }: ContentLibraryPageProps) {
  const { id } = await params;
  return <ContentLibrary subjectId={id} />;
}
