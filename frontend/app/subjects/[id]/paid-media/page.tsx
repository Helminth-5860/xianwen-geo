import { PaidMediaShoppingWorkspace } from "./paid-media-shopping-workspace";

type PaidMediaPageProps = Readonly<{
  params: Promise<{ id: string }>;
}>;

export default async function PaidMediaPage({ params }: PaidMediaPageProps) {
  const { id } = await params;

  return <PaidMediaShoppingWorkspace subjectId={id} />;
}
