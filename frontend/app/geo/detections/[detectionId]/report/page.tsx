"use client";

import { useParams } from "next/navigation";

import GeoReportPage from "../../../reports/report-page";

export default function DetectionReportPage() {
  const { detectionId } = useParams<{ detectionId: string }>();
  return <GeoReportPage detectionId={detectionId} />;
}
