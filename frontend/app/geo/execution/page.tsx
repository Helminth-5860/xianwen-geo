"use client";

import { ArrowRightOutlined, CalendarOutlined, CheckCircleOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Pagination,
  Progress,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getExecutionPlans,
  type ExecutionPlan,
  type ExecutionPlanPage,
} from "@/lib/strategy-execution-client";

import styles from "./execution-page.module.css";

const statusLabels = {
  active: { text: "执行中", color: "processing" },
  completed: { text: "已完成", color: "success" },
  cancelled: { text: "已取消", color: "error" },
} as const;

function statusOf(plan: ExecutionPlan) {
  const hasCompleted = plan.items.some((item) => item.status === "completed");
  const hasCancelled = plan.items.some((item) => item.status === "cancelled");
  if (plan.status === "cancelled" && hasCompleted && hasCancelled) {
    return { text: "部分完成", color: "warning" } as const;
  }
  return statusLabels[plan.status];
}

function progressOf(plan: ExecutionPlan) {
  if (plan.items.length === 0) return 0;
  return Math.round(
    (plan.items.filter((item) => item.status === "completed").length / plan.items.length) * 100,
  );
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

type PageState = Readonly<{ subjectId: string; page: number; result: ExecutionPlanPage }>;

export default function ExecutionPlanIndexPage() {
  const { currentSubject, loading: subjectLoading } = useSubjectWorkspace();
  const [pageSelection, setPageSelection] = useState({ subjectId: "", page: 1 });
  const [state, setState] = useState<PageState>();
  const [error, setError] = useState("");
  const subjectId = currentSubject?.id ?? "";
  const page = pageSelection.subjectId === subjectId ? pageSelection.page : 1;

  useEffect(() => {
    if (!subjectId || subjectLoading) return;
    let active = true;
    void getExecutionPlans(subjectId, page)
      .then((result) => {
        if (!active) return;
        setState({ subjectId, page, result });
        setError("");
      })
      .catch((reason) => {
        if (active) setError(userMessage(reason));
      });
    return () => {
      active = false;
    };
  }, [page, subjectId, subjectLoading]);

  const result = state?.subjectId === subjectId && state.page === page ? state.result : undefined;
  const items = useMemo(() => result?.items ?? [], [result]);

  if (subjectLoading || (subjectId && !result && !error)) {
    return <Spin fullscreen description="正在加载执行计划" />;
  }

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <Typography.Text type="secondary">优化中心</Typography.Text>
          <Typography.Title level={2}>执行计划</Typography.Title>
          <Typography.Paragraph type="secondary">
            把已确认的优化方案拆成可完成、可取消、可复测的行动步骤。
          </Typography.Paragraph>
        </div>
        <Button href="/geo/strategy">查看优化方案</Button>
      </header>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      {!currentSubject ? (
        <Card>
          <Empty description="请先绑定主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </Card>
      ) : (
        <>
          <section className={styles.subjectBar}>
            <div>
              <Typography.Text type="secondary">当前主体</Typography.Text>
              <Typography.Title level={3}>
                {currentSubject.official_name || currentSubject.subject_type.name}
              </Typography.Title>
            </div>
            <Tag>{result?.pagination.count ?? 0} 个执行计划</Tag>
          </section>

          {items.length === 0 ? (
            <Card>
              <Empty description="当前主体还没有执行计划">
                <Button type="primary" href="/geo/strategy">
                  从优化方案开始
                </Button>
              </Empty>
            </Card>
          ) : (
            <div className={styles.planList}>
              {items.map((plan) => {
                const status = statusOf(plan);
                const progress = progressOf(plan);
                return (
                  <article className={styles.planCard} key={plan.id}>
                    <div>
                      <div className={styles.planHeader}>
                        <div>
                          <Space wrap>
                            <Typography.Title level={3}>{plan.package_name}</Typography.Title>
                            <Tag color={status.color}>{status.text}</Tag>
                          </Space>
                          <div className={styles.planMeta}>
                            <span>
                              <CalendarOutlined /> 创建于 {formatDate(plan.created_at)}
                            </span>
                            <span>预计 {plan.estimated_days} 天</span>
                            <span>{plan.items.length} 项行动</span>
                            {plan.selected_media.length > 0 ? (
                              <span>{plan.selected_media.length} 家媒体</span>
                            ) : null}
                          </div>
                        </div>
                      </div>
                    </div>
                    <div className={styles.progressBlock}>
                      <div className={styles.progressHeader}>
                        <span>{progress === 100 ? <CheckCircleOutlined /> : null} 完成进度</span>
                        <strong>{progress}%</strong>
                      </div>
                      <Progress
                        percent={progress}
                        showInfo={false}
                        status={status.text === "已取消" ? "exception" : undefined}
                      />
                      <Button block type="primary" href={`/geo/execution/${plan.id}`}>
                        查看并执行 <ArrowRightOutlined />
                      </Button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}

          {(result?.pagination.total_pages ?? 0) > 1 ? (
            <Pagination
              current={page}
              pageSize={20}
              total={result?.pagination.count ?? 0}
              showSizeChanger={false}
              onChange={(nextPage) => setPageSelection({ subjectId, page: nextPage })}
            />
          ) : null}
        </>
      )}
    </main>
  );
}
