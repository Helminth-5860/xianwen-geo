"use client";

import { useParams } from "next/navigation";

import ImprovementStrategyPage from "./strategy-page";

export default function StrategyRoutePage() {
  const { reportId } = useParams<{ reportId: string }>();
  return <ImprovementStrategyPage reportId={reportId} />;
}
