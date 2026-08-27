import ImprovementStrategyPage from "../../reports/[reportId]/strategy/strategy-page";

type Props = Readonly<{
  params: Promise<{ reportId: string }>;
}>;

export default async function StrategyRoutePage({ params }: Props) {
  const { reportId } = await params;
  return <ImprovementStrategyPage reportId={reportId} />;
}
