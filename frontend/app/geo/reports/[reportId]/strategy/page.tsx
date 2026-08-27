import { redirect } from "next/navigation";

type Props = Readonly<{
  params: Promise<{ reportId: string }>;
}>;

export default async function LegacyStrategyRoutePage({ params }: Props) {
  const { reportId } = await params;
  redirect(`/geo/strategy/${reportId}`);
}
