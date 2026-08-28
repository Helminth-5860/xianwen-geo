import ExecutionPlanDetailPage from "./execution-plan-page";

export default async function ExecutionPlanPage({
  params,
}: Readonly<{ params: Promise<{ planId: string }> }>) {
  const { planId } = await params;
  return <ExecutionPlanDetailPage planId={planId} />;
}
