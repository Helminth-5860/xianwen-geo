"use client";

import { Button, Empty, Result, Spin } from "antd";
import { useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getReportHistory,
  getReportQuestions,
  type GeoReport,
  type ReportQuestionPage,
} from "@/lib/geo-report-client";

import { ExposureCockpitPage } from "./components/exposure-cockpit-page";
import { adaptExposureData } from "./exposure-data-adapter";
import styles from "./exposure-command-center.module.css";

type ExposureState = Readonly<{
  subjectId: string;
  reports: readonly GeoReport[];
  selectedReportId: string;
  error: string;
}>;

type QuestionsState = Readonly<{
  reportId: string;
  data: ReportQuestionPage | null;
}>;

export default function GeoExposurePage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [state, setState] = useState<ExposureState | null>(null);
  const [questionsState, setQuestionsState] = useState<QuestionsState | null>(null);
  const subjectId = subject?.id ?? "";

  useEffect(() => {
    if (subjectLoading || !subjectId) return;
    const controller = new AbortController();
    void getReportHistory(subjectId)
      .then((result) => {
        if (controller.signal.aborted) return;
        const reports = [...result.items].sort(
          (left, right) => Date.parse(right.generated_at) - Date.parse(left.generated_at),
        );
        setState({
          subjectId,
          reports,
          selectedReportId: reports[0]?.id ?? "",
          error: "",
        });
      })
      .catch((reason: unknown) => {
        if (controller.signal.aborted) return;
        setState({ subjectId, reports: [], selectedReportId: "", error: userMessage(reason) });
      });
    return () => controller.abort();
  }, [subjectId, subjectLoading]);

  const activeState = state?.subjectId === subjectId ? state : null;
  const report = activeState?.reports.find((item) => item.id === activeState.selectedReportId);

  useEffect(() => {
    if (!report) return;
    let current = true;
    void getReportQuestions(report.id, 1)
      .then((result) => {
        if (current) setQuestionsState({ reportId: report.id, data: result });
      })
      .catch(() => {
        if (current) setQuestionsState({ reportId: report.id, data: null });
      });
    return () => {
      current = false;
    };
  }, [report]);

  const questions =
    questionsState && questionsState.reportId === report?.id ? questionsState.data : null;

  const subjectName = subject?.official_name || subject?.subject_type.name || "当前主体";
  const data = useMemo(
    () =>
      report && activeState
        ? adaptExposureData({
            report,
            reports: activeState.reports,
            questions,
            subjectName,
          })
        : null,
    [activeState, questions, report, subjectName],
  );

  if (subjectLoading || (subject && !activeState)) {
    return <Spin fullscreen description="正在加载曝光态势" />;
  }

  if (!subject) {
    return (
      <main className={styles.statePage}>
        <Empty description="请先完善主体资料">
          <Button type="primary" href="/subjects">
            前往主体管理
          </Button>
        </Empty>
      </main>
    );
  }

  if (activeState?.error) {
    return (
      <main className={styles.statePage}>
        <Result
          status="warning"
          title="曝光数据暂时无法显示"
          subTitle={activeState.error}
          extra={<Button onClick={() => window.location.reload()}>重新加载</Button>}
        />
      </main>
    );
  }

  if (!report || !data || !activeState) {
    return (
      <main className={styles.statePage}>
        <Empty description="完成一次检测后，这里将展示曝光态势">
          <Button type="primary" href="/geo/detections">
            开始检测
          </Button>
        </Empty>
      </main>
    );
  }

  return (
    <ExposureCockpitPage
      data={data}
      reports={activeState.reports}
      subjectName={subjectName}
      selectedReportId={activeState.selectedReportId}
      onReportChange={(selectedReportId) =>
        setState((current) =>
          current?.subjectId === subjectId ? { ...current, selectedReportId } : current,
        )
      }
    />
  );
}
