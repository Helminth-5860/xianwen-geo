"use client";

import { Alert, Button, Card, Empty, Skeleton, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getCompetitorComparison,
  type CompetitorComparison,
  type CompetitorComparisonEntity,
  type CompetitorMetricValue,
  type CompetitorOpportunity,
} from "@/lib/competitors-client";

import styles from "./competitor-comparison.module.css";

const { Paragraph, Text, Title } = Typography;

function wasAborted(reason: unknown) {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function countValue(value: CompetitorMetricValue) {
  return value === null ? "—" : new Intl.NumberFormat("zh-CN").format(value);
}

function percentValue(value: CompetitorMetricValue) {
  return value === null ? "—" : `${Number(value).toFixed(2)}%`;
}

function formatDateTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

type MetricRow = Readonly<{
  key: string;
  label: string;
  format: (value: CompetitorMetricValue) => string;
  metric: keyof CompetitorComparisonEntity["metrics"];
}>;

const metricRows: MetricRow[] = [
  { key: "mentions", label: "AI 提及次数", metric: "mention_count", format: countValue },
  { key: "mention-rate", label: "AI 提及率", metric: "mention_rate", format: percentValue },
  {
    key: "coverage",
    label: "问题覆盖数",
    metric: "question_coverage_count",
    format: countValue,
  },
  {
    key: "coverage-rate",
    label: "问题覆盖率",
    metric: "question_coverage_rate",
    format: percentValue,
  },
  {
    key: "shared",
    label: "共同出现问题数",
    metric: "shared_question_count",
    format: countValue,
  },
  {
    key: "gaps",
    label: "机会缺口数",
    metric: "gap_question_count",
    format: countValue,
  },
  {
    key: "recommendation",
    label: "推荐率",
    metric: "recommendation_rate",
    format: percentValue,
  },
  { key: "citations", label: "引用数", metric: "citation_count", format: countValue },
];

export default function CompetitorComparisonPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const subjectId = subject?.id ?? "";
  const [data, setData] = useState<CompetitorComparison | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const requestSequence = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    const sequence = ++requestSequence.current;
    const timer = window.setTimeout(() => {
      setData(null);
      setError("");
      if (subjectLoading || !subjectId) {
        setLoading(false);
        return;
      }

      setLoading(true);
      void getCompetitorComparison(subjectId, controller.signal)
        .then((result) => {
          if (sequence !== requestSequence.current || result.subject_id !== subjectId) return;
          setData(result);
        })
        .catch((reason: unknown) => {
          if (sequence === requestSequence.current && !wasAborted(reason)) {
            setError(userMessage(reason));
          }
        })
        .finally(() => {
          if (sequence === requestSequence.current) setLoading(false);
        });
    }, 0);

    return () => {
      window.clearTimeout(timer);
      controller.abort();
      requestSequence.current += 1;
    };
  }, [subjectId, subjectLoading]);

  const entities = useMemo(() => data?.entities ?? [], [data?.entities]);
  const metricColumns = useMemo(
    () => [
      {
        title: "核心指标",
        dataIndex: "label",
        key: "label",
        fixed: "left" as const,
        width: 170,
      },
      ...entities.map((entity) => ({
        title: entity.name,
        key: entity.id,
        width: 170,
        render: (_: unknown, row: MetricRow) => row.format(entity.metrics[row.metric]),
      })),
    ],
    [entities],
  );
  const opportunityColumns = useMemo(
    () => [
      {
        title: "问题",
        dataIndex: "question",
        key: "question",
        fixed: "left" as const,
        width: 320,
      },
      ...entities.map((entity) => ({
        title: entity.name,
        key: entity.id,
        width: 150,
        align: "center" as const,
        render: (_: unknown, row: CompetitorOpportunity) =>
          entity.kind === "competitor" && row.competitor_ids.includes(entity.id) ? (
            <Tag color="green">已出现</Tag>
          ) : (
            "—"
          ),
      })),
    ],
    [entities],
  );

  const subjectName = data?.subject_name || subject?.official_name || subject?.subject_type.name;

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">数据中心</Text>
          <Title level={2}>竞品对比</Title>
          <Paragraph type="secondary">
            使用已有检测结果，对比当前主体与核心竞品的真实提及和问题覆盖表现。
          </Paragraph>
        </div>
      </section>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      {!subjectLoading && !subject ? (
        <Card className={styles.emptyCard}>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              前往主体管理
            </Button>
          </Empty>
        </Card>
      ) : (
        <>
          <section className="geo-dashboard__subject-bar">
            <div>
              <Text type="secondary">当前主体</Text>
              <Title level={3}>{subjectName || "正在读取主体信息"}</Title>
            </div>
            {data ? <Tag color="blue">已设置 {data.competitor_count} / 3 家竞品</Tag> : null}
          </section>

          {loading || subjectLoading ? (
            <Card>
              <Skeleton active paragraph={{ rows: 7 }} />
            </Card>
          ) : data?.status === "no_competitors" ? (
            <Card className={styles.emptyCard}>
              <Empty
                description={
                  <Space orientation="vertical" size={4}>
                    <Text strong>尚未设置核心竞品</Text>
                    <Text type="secondary">
                      请先为当前主体设置最多 3 家核心竞品，再进行竞品对比分析。
                    </Text>
                  </Space>
                }
              >
                <Button type="primary" href={`/subjects/${subjectId}/competitors`}>
                  前往竞品管理
                </Button>
              </Empty>
            </Card>
          ) : data?.status === "no_detection_data" ? (
            <Card className={styles.emptyCard}>
              <Empty
                description={
                  <Space orientation="vertical" size={4}>
                    <Text strong>已设置竞品，但当前暂无足够检测数据用于对比。</Text>
                    <Text type="secondary">请先完成检测后再查看竞品表现。</Text>
                  </Space>
                }
              >
                <Button type="primary" href="/geo/detections">
                  前往检测中心
                </Button>
              </Empty>
            </Card>
          ) : data?.status === "ready" ? (
            <>
              <Space wrap>
                <Tag color="blue">{data.question_count} 个检测问题</Tag>
                <Tag color="green">{data.valid_answer_count} 个有效回答</Tag>
                <Text type="secondary">结果生成于 {formatDateTime(data.generated_at)}</Text>
                {data.detail_url ? (
                  <Link href={data.detail_url}>查看检测详情</Link>
                ) : data.report_id ? (
                  <Link href={`/geo/reports/${data.report_id}`}>查看检测详情</Link>
                ) : null}
              </Space>

              <section className={styles.entityGrid} aria-label="主体与竞品概览">
                {entities.map((entity) => (
                  <Card key={entity.id} className={styles.entityCard}>
                    <Tag color={entity.kind === "subject" ? "blue" : "default"}>
                      {entity.kind === "subject" ? "当前主体" : "核心竞品"}
                    </Tag>
                    <Title level={4} className={styles.entityName}>
                      {entity.name}
                    </Title>
                    <div className={styles.entityMetrics}>
                      <div className={styles.entityMetric}>
                        <span>AI 提及次数</span>
                        <strong>{countValue(entity.metrics.mention_count)}</strong>
                      </div>
                      <div className={styles.entityMetric}>
                        <span>问题覆盖率</span>
                        <strong>{percentValue(entity.metrics.question_coverage_rate)}</strong>
                      </div>
                    </div>
                  </Card>
                ))}
              </section>

              <Card title="核心指标对比" className={styles.tableCard}>
                <Table<MetricRow>
                  rowKey="key"
                  columns={metricColumns}
                  dataSource={metricRows}
                  pagination={false}
                  scroll={{ x: Math.max(680, 170 * (entities.length + 1)) }}
                />
                <Paragraph type="secondary" style={{ margin: "16px 0 0" }}>
                  推荐率和引用数只在已有检测数据能够可靠确认时展示；暂无足够数据时显示“—”。
                </Paragraph>
              </Card>

              <Card title="抢答问题与机会缺口" className={styles.tableCard}>
                {data.opportunities.length ? (
                  <Table<CompetitorOpportunity>
                    rowKey="question_id"
                    dataSource={data.opportunities}
                    pagination={{ pageSize: 20, showSizeChanger: false, hideOnSinglePage: true }}
                    columns={opportunityColumns}
                    scroll={{ x: Math.max(680, 320 + 150 * entities.length) }}
                  />
                ) : (
                  <Empty description="当前检测结果中暂未发现竞品领先的机会问题" />
                )}
              </Card>
            </>
          ) : null}
        </>
      )}
    </main>
  );
}
