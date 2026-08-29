import { CompetitorManagementWorkspace } from "./competitor-management-workspace";

type CompetitorManagementPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function CompetitorManagementPage({ params }: CompetitorManagementPageProps) {
  const { id } = await params;
  return <CompetitorManagementWorkspace subjectId={id} />;
}
