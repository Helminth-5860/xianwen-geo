"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Col,
  Divider,
  List,
  Modal,
  Pagination,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  adjustedRetest,
  createReportExport,
  getDetectionOptions,
  getReport,
  getReportAnswer,
  getReportExport,
  getReportForDetection,
  getReportHistory,
  getReportQuestions,
  getReportTrends,
  quickRetest,
  type GeoReport,
  type ReportAnswer,
  type ReportExport,
  type ReportQuestionPage,
  type ReportTrend,
} from "@/lib/geo-report-client";
import { getCurrentQuestionBank, type QuestionBankVersion } from "@/lib/question-bank-client";

export const REPORT_READY_POLL_INTERVAL_MS = 2000;
export const REPORT_EXPORT_POLL_INTERVAL_MS = 1200;

const dimensionLabels: Record<string, string> = {
  mention: "提及",
  recommendation: "推荐",
  rank: "排名",
  accuracy: "准确性",
  sentiment: "情感",
  citation: "引用",
};

const exportLabels: Record<ReportExport["format"], string> = {
  pdf: "PDF",
  word: "Word",
  excel: "Excel",
};

const quickBlockReasons: Record<string, string> = {
  model_not_entitled: "原报告模型已不在当前套餐权限内",
  model_disabled: "原报告模型当前已停用",
  model_paused: "原报告模型正在维护暂停",
  runtime_missing: "原报告模型缺少运行配置",
  runtime_unavailable: "原报告模型运行环境暂不可用",
  credential_unavailable: "原报告模型凭据暂不可用",
  adapter_unavailable: "原报告模型适配器暂不可用",
};

export function quickRetestBlockedMessage(reason: unknown): string {
  if (reason instanceof AuthApiError && reason.code === "GEO_DETECTION_PROVIDER_UNAVAILABLE") {
    const reasonCode = String(reason.details.reason || "runtime_unavailable");
    const modelKey = String(reason.details.model_key || "原模型");
    return `${modelKey}：${quickBlockReasons[reasonCode] || "原模型当前不可执行"}。可稍后重试、恢复套餐或运行权限，或使用调整后复测重新选择；系统不会静默替换模型。`;
  }
  return userMessage(reason);
}

type Props = Readonly<
  { detectionId: string; reportId?: never } | { reportId: string; detectionId?: never }
>;

export default function GeoReportPage(props: Props) {
  const router = useRouter();
  const [report, setReport] = useState<GeoReport>();
  const [questions, setQuestions] = useState<ReportQuestionPage>();
  const [page, setPage] = useState(1);
  const [answers, setAnswers] = useState<Record<string, ReportAnswer>>({});
  const [answerLoading, setAnswerLoading] = useState<string>();
  const [history, setHistory] = useState<GeoReport[]>([]);
  const [trends, setTrends] = useState<ReportTrend[]>([]);
  const [exports, setExports] = useState<Partial<Record<ReportExport["format"], ReportExport>>>({});
  const [pendingScoring, setPendingScoring] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [adjustedOpen, setAdjustedOpen] = useState(false);
  const [currentBank, setCurrentBank] = useState<QuestionBankVersion>();
  const [modelOptions, setModelOptions] = useState<
    Array<{ label: string; value: string; disabled: boolean }>
  >([]);
  const [selectedQuestions, setSelectedQuestions] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);

  const loadReport = useCallback(async () => {
    try {
      const next = props.detectionId
        ? await getReportForDetection(props.detectionId)
        : await getReport(props.reportId!);
      setReport(next);
      setPendingScoring(false);
      setError("");
    } catch (reason) {
      if (
        props.detectionId &&
        reason instanceof AuthApiError &&
        reason.code === "GEO_DETECTION_STATE_CONFLICT"
      ) {
        setPendingScoring(true);
        setError("");
      } else {
        setError(userMessage(reason));
      }
    }
  }, [props.detectionId, props.reportId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadReport(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReport]);

  useEffect(() => {
    if (!pendingScoring) return;
    const timer = window.setTimeout(() => void loadReport(), REPORT_READY_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [loadReport, pendingScoring]);

  useEffect(() => {
    if (!report) return;
    void Promise.all([
      getReportQuestions(report.id, page),
      getReportHistory(report.subject_id),
      getReportTrends(report.subject_id),
    ])
      .then(([detail, historical, trendData]) => {
        setQuestions(detail);
        setHistory(historical.items);
        setTrends(trendData.items);
      })
      .catch((reason) => setError(userMessage(reason)));
  }, [page, report]);

  useEffect(() => {
    const active = Object.values(exports).filter((item): item is ReportExport =>
      Boolean(item && ["queued", "running"].includes(item.status)),
    );
    if (!active.length) return;
    const timer = window.setTimeout(() => {
      void Promise.all(active.map((item) => getReportExport(item.id))).then((items) => {
        setExports((current) => {
          const next = { ...current };
          for (const item of items) next[item.format] = item;
          return next;
        });
      });
    }, REPORT_EXPORT_POLL_INTERVAL_MS);
    return () => window.clearTimeout(timer);
  }, [exports]);

  const baselineModels = useMemo(
    () => report?.provenance.models.map((row) => row.model_key).join("、") || "",
    [report],
  );

  const loadAnswer = async (callId: string) => {
    if (answers[callId]) return;
    setAnswerLoading(callId);
    try {
      const answer = await getReportAnswer(callId);
      setAnswers((current) => ({ ...current, [callId]: answer }));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setAnswerLoading(undefined);
    }
  };

  const startExport = async (format: ReportExport["format"]) => {
    if (!report) return;
    setBusy(true);
    try {
      const created = await createReportExport(report.id, format);
      setExports((current) => ({
        ...current,
        [format]: {
          id: created.id,
          report_id: report.id,
          format,
          status: created.status,
          safe_error_code: "",
          download_url: null,
          expires_at: null,
          expired: false,
        },
      }));
      setNotice(`${exportLabels[format]} 导出任务已创建`);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const startQuickRetest = async () => {
    if (!report) return;
    setBusy(true);
    try {
      const created = await quickRetest(report.id, crypto.randomUUID());
      router.push(`/geo/detections/${created.detection_id}`);
    } catch (reason) {
      setError(quickRetestBlockedMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const openAdjusted = async () => {
    if (!report) return;
    setBusy(true);
    try {
      const [bank, options] = await Promise.all([
        getCurrentQuestionBank(report.subject_id),
        getDetectionOptions(report.subject_id),
      ]);
      setCurrentBank(bank);
      setSelectedQuestions(
        (bank.items || []).slice(0, options.max_questions_per_detection).map((row) => row.id),
      );
      const available = options.models.filter(
        (row) => row.enabled && !row.paused && row.configured,
      );
      setModelOptions(
        options.models.map((row) => ({
          label: row.display_name,
          value: row.id,
          disabled: !row.enabled || row.paused || !row.configured,
        })),
      );
      setSelectedModels(
        available
          .filter((row) => row.selected_by_default)
          .slice(0, options.max_models_per_detection)
          .map((row) => row.id),
      );
      setAdjustedOpen(true);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const submitAdjusted = async () => {
    if (!report || !selectedQuestions.length || !selectedModels.length) {
      setError("调整后复测至少选择一个当前问题和一个当前可用模型");
      return;
    }
    setBusy(true);
    try {
      const created = await adjustedRetest(
        report.id,
        selectedQuestions,
        selectedModels,
        crypto.randomUUID(),
      );
      setAdjustedOpen(false);
      router.push(`/geo/detections/${created.detection_id}`);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (!report && !error) {
    return (
      <Spin
        fullscreen
        description={pendingScoring ? "检测已结束，正在完成评分与报告固化" : "正在加载报告"}
      />
    );
  }

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap align="baseline">
          <Typography.Title level={2}>GEO 检测报告</Typography.Title>
          {report && <Tag color="blue">评分规则 {report.provenance.scoring_rule_version}</Tag>}
        </Space>
        {error && <Alert type="error" showIcon title={error} />}
        {notice && <Alert type="success" showIcon title={notice} />}
        {pendingScoring && (
          <Alert type="info" showIcon title="检测已终结，语义评分完成后将生成不可修改的正式报告" />
        )}
        {report && (
          <>
            {report.comparison?.subject_version_changed && (
              <Alert
                type="warning"
                showIcon
                title="主体资料版本已变化；本报告使用复测时的当前版本"
              />
            )}
            {report.comparison?.status === "not_comparable" && (
              <Alert
                type="warning"
                showIcon
                title="不可正式比较 / 无正式涨跌"
                description={
                  report.comparison.scoring_version_changed
                    ? "评分规则版本已变化；历史报告不会用新规则重算。"
                    : "实际问题或逻辑模型集合不同，仅可并排查看。"
                }
              />
            )}

            <Row gutter={[16, 16]}>
              <Col xs={24} md={8}>
                <Card>
                  <Statistic
                    title="GEO 综合得分"
                    value={report.summary.geo.score || "-"}
                    suffix={report.summary.geo.grade}
                  />
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card>
                  <Statistic
                    title="品牌认知与口碑"
                    value={report.summary.brand_reputation.score || "-"}
                    suffix={report.summary.brand_reputation.grade}
                  />
                </Card>
              </Col>
              <Col xs={24} md={8}>
                <Card>
                  <Statistic
                    title="曝光潜力指数"
                    value={report.summary.exposure.exposure_index}
                    suffix={report.summary.exposure.grade}
                  />
                </Card>
              </Col>
            </Row>
            <Alert type="info" showIcon title={report.summary.exposure.disclaimer} />

            <Card title="六维评分">
              <Row gutter={[16, 16]}>
                {Object.entries(report.summary.dimensions).map(([key, value]) => (
                  <Col xs={12} md={8} lg={4} key={key}>
                    <Statistic title={dimensionLabels[key] || key} value={value || "-"} />
                  </Col>
                ))}
              </Row>
            </Card>

            <Card title="模型独立得分">
              <List
                dataSource={report.summary.models}
                renderItem={(model) => (
                  <List.Item>
                    <List.Item.Meta
                      title={model.model_key}
                      description={`成功 ${model.successful_calls}/${model.planned_calls}`}
                    />
                    <Space wrap>
                      <Tag color="blue">GEO {model.geo?.score || "-"}</Tag>
                      <Tag>口碑 {model.brand_reputation?.score || "-"}</Tag>
                      <Tag>{model.geo?.status || model.status}</Tag>
                    </Space>
                  </List.Item>
                )}
              />
            </Card>

            <Card title="主要竞品曝光参考">
              {report.summary.competitors.length ? (
                <List
                  dataSource={report.summary.competitors}
                  renderItem={(item) => (
                    <List.Item extra={<Tag>提及 {item.mention_count}</Tag>}>
                      <List.Item.Meta
                        title={item.canonical_name}
                        description={item.aliases.join("、") || "无别名"}
                      />
                    </List.Item>
                  )}
                />
              ) : (
                <Typography.Text type="secondary">
                  本次没有形成可展示的竞品曝光参考。
                </Typography.Text>
              )}
            </Card>

            <Card title="按问题分组明细">
              {!questions ? (
                <Spin />
              ) : (
                <Space orientation="vertical" size="large" style={{ width: "100%" }}>
                  {questions.results.map((question) => (
                    <Card
                      key={question.question_id}
                      size="small"
                      title={question.text}
                      extra={
                        <Tag>{question.question_type === "natural" ? "自然探索" : "品牌指向"}</Tag>
                      }
                    >
                      <List
                        dataSource={question.results}
                        renderItem={(result) => (
                          <List.Item>
                            <Space orientation="vertical" style={{ width: "100%" }}>
                              <Space wrap>
                                <Typography.Text strong>{result.model_key}</Typography.Text>
                                <Tag>{result.status}</Tag>
                                {result.score?.total && (
                                  <Tag color="blue">单题 {result.score.total}</Tag>
                                )}
                              </Space>
                              <Typography.Paragraph>
                                {result.snippet || "暂无成功回答"}
                              </Typography.Paragraph>
                              {result.answer_available && !answers[result.call_id] && (
                                <Button
                                  size="small"
                                  loading={answerLoading === result.call_id}
                                  onClick={() => void loadAnswer(result.call_id)}
                                >
                                  展开完整原始回答
                                </Button>
                              )}
                              {answers[result.call_id] && (
                                <Card size="small" title="完整原始回答">
                                  <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                                    {answers[result.call_id].answer}
                                  </Typography.Paragraph>
                                </Card>
                              )}
                              {result.citations.map((citation) => (
                                <Typography.Link
                                  key={citation.url}
                                  href={citation.url}
                                  target="_blank"
                                  rel="noreferrer"
                                >
                                  {citation.title || citation.source_name || citation.url}
                                </Typography.Link>
                              ))}
                            </Space>
                          </List.Item>
                        )}
                      />
                    </Card>
                  ))}
                  <Pagination
                    current={questions.pagination.page}
                    pageSize={questions.pagination.page_size}
                    total={questions.pagination.count}
                    showSizeChanger={false}
                    onChange={setPage}
                  />
                </Space>
              )}
            </Card>

            <Card title="历史与可比趋势">
              <List
                dataSource={trends}
                locale={{ emptyText: "暂无历史趋势" }}
                renderItem={(item) => (
                  <List.Item>
                    <Space wrap>
                      <Typography.Link
                        onClick={() => router.push(`/geo/reports/${item.report_id}`)}
                      >
                        {new Date(item.generated_at).toLocaleString()}
                      </Typography.Link>
                      <Tag>GEO {item.geo_score || "-"}</Tag>
                      {item.comparison?.subject_version_changed && (
                        <Tag color="orange">主体版本变化</Tag>
                      )}
                      {item.comparison?.geo_score_delta && (
                        <Tag color="blue">涨跌 {item.comparison.geo_score_delta}</Tag>
                      )}
                    </Space>
                  </List.Item>
                )}
              />
              <Typography.Text type="secondary">
                共 {history.length}{" "}
                份不可修改的历史报告；只有问题、逻辑模型和评分规则完全一致时连接正式趋势。
              </Typography.Text>
            </Card>

            <Card title="导出与复测">
              <Space orientation="vertical" style={{ width: "100%" }}>
                <Space wrap>
                  <Button
                    type="primary"
                    onClick={() => router.push(`/geo/reports/${report.id}/strategy`)}
                  >
                    生成改善策略
                  </Button>
                  <Typography.Text type="secondary">
                    基于本报告不可修改的事实生成，不会重新检测或评分。
                  </Typography.Text>
                </Space>
                <Divider />
                <Space wrap>
                  {(["pdf", "word", "excel"] as const).map((format) => {
                    const item = exports[format];
                    return item?.download_url ? (
                      <Button key={format} type="link" href={item.download_url}>
                        下载 {exportLabels[format]}
                      </Button>
                    ) : (
                      <Button
                        key={format}
                        loading={Boolean(item && ["queued", "running"].includes(item.status))}
                        disabled={busy}
                        onClick={() => void startExport(format)}
                      >
                        导出 {exportLabels[format]}
                      </Button>
                    );
                  })}
                </Space>
                <Divider />
                <Typography.Text>
                  快速复测沿用原报告的冻结问题和精确逻辑模型集合（{baselineModels}
                  ），使用当前主体版本和当前评分规则；不会替换不可用模型。
                </Typography.Text>
                <Space wrap>
                  <Button type="primary" loading={busy} onClick={() => void startQuickRetest()}>
                    快速复测
                  </Button>
                  <Button disabled={busy} onClick={() => void openAdjusted()}>
                    调整后复测
                  </Button>
                </Space>
              </Space>
            </Card>
          </>
        )}
      </Space>

      <Modal
        title="调整后复测"
        open={adjustedOpen}
        confirmLoading={busy}
        onCancel={() => setAdjustedOpen(false)}
        onOk={() => void submitAdjusted()}
        okText="创建独立复测"
        cancelText="取消"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            title="按当前合法问题和模型创建新的独立检测；是否可比将由最终冻结事实决定。"
          />
          <Typography.Text strong>当前问题</Typography.Text>
          <Checkbox.Group
            value={selectedQuestions}
            onChange={(values) => setSelectedQuestions(values as string[])}
            options={(currentBank?.items || []).map((row) => ({ label: row.text, value: row.id }))}
          />
          <Typography.Text strong>当前模型</Typography.Text>
          <Checkbox.Group
            value={selectedModels}
            onChange={(values) => setSelectedModels(values as string[])}
            options={modelOptions}
          />
        </Space>
      </Modal>
    </main>
  );
}
