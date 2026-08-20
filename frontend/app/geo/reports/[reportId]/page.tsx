"use client";

import { useParams } from "next/navigation";

import GeoReportPage from "../report-page";

export default function ReportByIdPage() {
  const { reportId } = useParams<{ reportId: string }>();
  return <GeoReportPage reportId={reportId} />;
}
