"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getReportComparison,
  getReportHistory,
  type GeoReport,
  type GeoReportPairComparison,
} from "@/lib/geo-report-client";

const { Paragraph, Text, Title } = Typography;

const dimensionLabels: Readonly<Record<string, string>> = {
  mention: "提及",
  recommendation: "推荐",
  rank: "排名",
  accuracy: "准确性",
  sentiment: "情感",
  citation: "引用",
};

type HistoryState = Readonly<{
  subjectId: string;
  reports: GeoReport[];
  currentReportId: string;
  baselineReportId: string;
  error: string;
}>;

type ComparisonState = Readonly<{
  key: string;
  result?: GeoReportPairComparison;
  error: string;
}>;

function reportOptionLabel(report: GeoReport) {
  return `${new Date(report.generated_at).toLocaleString("zh-CN")} · GEO ${report.summary.geo.score ?? "—"}`;
}

function deltaValue(value: string | null) {
  if (value === null) return "—";
  return Number(value) > 0 ? `+${value}` : value;
}

function notComparableReasons(comparison: GeoReportPairComparison["comparison"]) {
  const reasons: string[] = [];
  if (!comparison.same_subject) reasons.push("所属主体不同");
  if (!comparison.same_questions) reasons.push("检测问题集合不同");
  if (!comparison.same_models) reasons.push("检测模型不同");
  if (!comparison.same_scoring_rule) reasons.push("评分口径不同");
  return reasons.length ? reasons.join("；") : "两份报告的检测条件不一致";
}

export default function GeoReportHistoryPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [historyState, setHistoryState] = useState<HistoryState>();
  const [comparisonState, setComparisonState] = useState<ComparisonState>();
  const subjectId = subject?.id ?? "";

  useEffect(() => {
    if (subjectLoading || !subjectId) return;
    let current = true;

    void getReportHistory(subjectId)
      .then((result) => {
        if (!current) return;
        const reports = [...result.items].sort(
          (left, right) =>
            new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
        );
        setHistoryState({
          subjectId,
          reports,
          currentReportId: reports[0]?.id ?? "",
          baselineReportId: reports[1]?.id ?? "",
          error: "",
        });
      })
      .catch((reason) => {
        if (current) {
          setHistoryState({
            subjectId,
            reports: [],
            currentReportId: "",
            baselineReportId: "",
            error: userMessage(reason),
          });
        }
      });

    return () => {
      current = false;
    };
  }, [subjectId, subjectLoading]);

  const state = historyState?.subjectId === subjectId ? historyState : undefined;
  const currentReportId = state?.currentReportId ?? "";
  const baselineReportId = state?.baselineReportId ?? "";
  const comparisonKey =
    subjectId && currentReportId && baselineReportId
      ? `${subjectId}:${currentReportId}:${baselineReportId}`
      : "";

  useEffect(() => {
    if (!comparisonKey) return;
    let current = true;

    void getReportComparison(currentReportId, baselineReportId)
      .then((result) => {
        if (current) setComparisonState({ key: comparisonKey, result, error: "" });
      })
      .catch((reason) => {
        if (current) {
          setComparisonState({ key: comparisonKey, error: userMessage(reason) });
        }
      });

    return () => {
      current = false;
    };
  }, [baselineReportId, comparisonKey, currentReportId]);

  const result = comparisonState?.key === comparisonKey ? comparisonState.result : undefined;
  const comparisonError = comparisonState?.key === comparisonKey ? comparisonState.error : "";
  const reportOptions = useMemo(
    () =>
      (state?.reports ?? []).map((report) => ({
        label: reportOptionLabel(report),
        value: report.id,
      })),
    [state?.reports],
  );

  if (subjectLoading || (subject && !state)) {
    return <Spin fullscreen description="正在加载历史报告" />;
  }

  const updateSelection = (field: "currentReportId" | "baselineReportId", value: string) => {
    setHistoryState((current) =>
      current && current.subjectId === subjectId ? { ...current, [field]: value } : current,
    );
  };

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">GEO 报告对比</Text>
          <Title level={2}>历史报告对比</Title>
          <Paragraph type="secondary">
            选择当前报告与基准报告，系统会核对两次检测的问题、模型和评分口径，再展示可比变化。
          </Paragraph>
        </div>
        <Space wrap>
          <Button href="/geo/reports">查看最新检测报告</Button>
          <Button href="/geo/detections">新建检测</Button>
        </Space>
      </section>

      {!subject ? (
        <Card>
          <Empty description="请先绑定主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </Card>
      ) : (
        <>
          <section className="geo-dashboard__subject-bar">
            <div>
              <Text type="secondary">当前主体</Text>
              <Title level={3}>{subject.official_name || subject.subject_type.name}</Title>
            </div>
            <Tag>历史报告 {state?.reports.length ?? 0}</Tag>
          </section>

          {state?.error && <Alert type="error" showIcon message={state.error} />}

          {!state?.error && state?.reports.length === 0 ? (
            <Card>
              <Empty description="当前主体还没有可对比的检测报告">
                <Button type="primary" href="/geo/detections">
                  开始首次检测
                </Button>
              </Empty>
            </Card>
          ) : !state?.error && state?.reports.length === 1 ? (
            <Card>
              <Empty description="至少需要两份检测报告才能进行真实对比">
                <Button type="primary" href={`/geo/reports/${state.reports[0].id}`}>
                  查看现有报告
                </Button>
              </Empty>
            </Card>
          ) : !state?.error ? (
            <>
              <Card title="选择两份报告">
                <Row gutter={[16, 16]}>
                  <Col xs={24} lg={12}>
                    <Text strong>当前报告</Text>
                    <Select
                      aria-label="当前报告"
                      value={state?.currentReportId}
                      style={{ width: "100%", marginTop: 8 }}
                      options={reportOptions.map((option) => ({
                        ...option,
                        disabled: option.value === state?.baselineReportId,
                      }))}
                      onChange={(value) => updateSelection("currentReportId", value)}
                    />
                  </Col>
                  <Col xs={24} lg={12}>
                    <Text strong>基准报告</Text>
                    <Select
                      aria-label="基准报告"
                      value={state?.baselineReportId}
                      style={{ width: "100%", marginTop: 8 }}
                      options={reportOptions.map((option) => ({
                        ...option,
                        disabled: option.value === state?.currentReportId,
                      }))}
                      onChange={(value) => updateSelection("baselineReportId", value)}
                    />
                  </Col>
                </Row>
              </Card>

              {comparisonError ? (
                <Alert type="error" showIcon message={comparisonError} />
              ) : !result ? (
                <Card>
                  <Spin description="正在核验两份报告的可比性" />
                </Card>
              ) : (
                <>
                  <Alert
                    type={result.comparison.status === "comparable" ? "success" : "warning"}
                    showIcon
                    title={
                      result.comparison.status === "comparable"
                        ? "两份报告可正式比较"
                        : "两份报告不可正式比较"
                    }
                    description={
                      result.comparison.status === "comparable"
                        ? "下列变化基于相同的检测问题、模型和评分口径计算。"
                        : `${notComparableReasons(result.comparison)}；仅可并排查看原始分值，不展示正式涨跌。`
                    }
                  />

                  <Card
                    title="核心指标涨跌"
                    extra={
                      <Space wrap>
                        <Button size="small" href={`/geo/reports/${result.current.id}`}>
                          当前报告
                        </Button>
                        <Button size="small" href={`/geo/reports/${result.baseline.id}`}>
                          基准报告
                        </Button>
                      </Space>
                    }
                  >
                    <Row gutter={[16, 16]}>
                      {[
                        {
                          key: "geo",
                          title: "GEO 综合得分",
                          current: result.current.summary.geo.score,
                          baseline: result.baseline.summary.geo.score,
                          delta: result.comparison.geo_score_delta,
                        },
                        {
                          key: "reputation",
                          title: "品牌认知与口碑",
                          current: result.current.summary.brand_reputation.score,
                          baseline: result.baseline.summary.brand_reputation.score,
                          delta: result.comparison.brand_reputation_score_delta,
                        },
                        {
                          key: "exposure",
                          title: "曝光指数",
                          current: result.current.summary.exposure.exposure_index,
                          baseline: result.baseline.summary.exposure.exposure_index,
                          delta: result.comparison.exposure_index_delta,
                        },
                      ].map((metric) => (
                        <Col xs={24} md={8} key={metric.key}>
                          <Card size="small">
                            <Statistic title={metric.title} value={metric.current ?? "—"} />
                            <Space wrap>
                              <Text type="secondary">基准 {metric.baseline ?? "—"}</Text>
                              {result.comparison.status === "comparable" && (
                                <Tag color="blue">涨跌 {deltaValue(metric.delta)}</Tag>
                              )}
                            </Space>
                          </Card>
                        </Col>
                      ))}
                    </Row>
                  </Card>

                  <Card title="六维评分涨跌">
                    <Row gutter={[16, 16]}>
                      {Object.entries(result.current.summary.dimensions).map(([key, value]) => (
                        <Col xs={12} md={8} lg={4} key={key}>
                          <Statistic
                            title={dimensionLabels[key] || "其他指标"}
                            value={value ?? "—"}
                          />
                          <Space orientation="vertical" size={0}>
                            <Text type="secondary">
                              基准 {result.baseline.summary.dimensions[key] ?? "—"}
                            </Text>
                            {result.comparison.status === "comparable" && (
                              <Tag color="blue">
                                涨跌 {deltaValue(result.comparison.dimension_deltas[key] ?? null)}
                              </Tag>
                            )}
                          </Space>
                        </Col>
                      ))}
                    </Row>
                  </Card>

                  {result.comparison.subject_version_changed && (
                    <Alert
                      type="info"
                      showIcon
                      title="两份报告基于不同时间的主体资料；历史报告内容不会因此改变。"
                    />
                  )}
                </>
              )}
            </>
          ) : null}
        </>
      )}
    </main>
  );
}
