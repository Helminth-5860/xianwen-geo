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
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";
import { ReportSharing } from "@/components/report-sharing";
import {
  adjustedRetest,
  createReportExport,
  getDetectionOptions,
  getReport,
  getReportAnswer,
  getReportExport,
  getReportForDetection,
  getReportQuestions,
  quickRetest,
  type GeoReport,
  type ReportAnswer,
  type ReportExport,
  type ReportQuestionPage,
} from "@/lib/geo-report-client";
import { getCurrentQuestionBank, type QuestionBankVersion } from "@/lib/question-bank-client";
import { aiModelDisplayName } from "@/lib/product-copy";

export const REPORT_READY_POLL_INTERVAL_MS = 2000;
export const REPORT_READY_MAX_POLL_ATTEMPTS = 15;
export const REPORT_EXPORT_POLL_INTERVAL_MS = 1200;

const REPORT_SCORING_UNAVAILABLE_MESSAGE =
  "检测已经完成，但报告暂未生成。检测结果不会丢失，请稍后点击“重新检查报告”。";

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
  word: "Word 文档",
  excel: "Excel 表格",
};

const quickBlockReasons: Record<string, string> = {
  model_not_entitled: "该模型不在当前套餐范围内",
  model_disabled: "该模型暂不可用",
  model_paused: "该模型正在维护",
  runtime_missing: "该模型服务暂不可用",
  runtime_unavailable: "该模型服务暂不可用",
  credential_unavailable: "该模型服务暂不可用",
  adapter_unavailable: "该模型服务暂不可用",
};

const reportStatusLabels: Readonly<Record<string, string>> = {
  queued: "等待中",
  running: "处理中",
  partial: "部分完成",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已取消",
  formal: "正式结果",
  reference: "参考结果",
  not_generated: "未生成",
};

function reportStatusLabel(status: string) {
  return reportStatusLabels[status] ?? "状态待确认";
}

export function quickRetestBlockedMessage(reason: unknown): string {
  if (reason instanceof AuthApiError && reason.code === "GEO_DETECTION_PROVIDER_UNAVAILABLE") {
    const reasonCode = String(reason.details.reason || "runtime_unavailable");
    const modelName = aiModelDisplayName(String(reason.details.model_key || ""));
    return `${modelName}：${quickBlockReasons[reasonCode] || "该模型当前不可用"}。可稍后重试、调整套餐，或使用调整后复测重新选择；系统不会自动改用其他模型。`;
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
  const reportReadyPollAttempts = useRef(0);
  const reportLoadInFlight = useRef(false);

  const loadReport = useCallback(async () => {
    if (reportLoadInFlight.current) return;
    reportLoadInFlight.current = true;
    try {
      const next = props.detectionId
        ? await getReportForDetection(props.detectionId)
        : await getReport(props.reportId!);
      setReport(next);
      reportReadyPollAttempts.current = 0;
      setPendingScoring(false);
      setError("");
    } catch (reason) {
      if (
        props.detectionId &&
        reason instanceof AuthApiError &&
        reason.code === "GEO_DETECTION_STATE_CONFLICT"
      ) {
        reportReadyPollAttempts.current += 1;
        if (reportReadyPollAttempts.current >= REPORT_READY_MAX_POLL_ATTEMPTS) {
          setPendingScoring(false);
          setError(REPORT_SCORING_UNAVAILABLE_MESSAGE);
        } else {
          setPendingScoring(true);
          setError("");
        }
      } else {
        setPendingScoring(false);
        setError(userMessage(reason));
      }
    } finally {
      reportLoadInFlight.current = false;
    }
  }, [props.detectionId, props.reportId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadReport(), 0);
    return () => window.clearTimeout(timer);
  }, [loadReport]);

  useEffect(() => {
    if (!pendingScoring) return;
    const timer = window.setInterval(() => void loadReport(), REPORT_READY_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadReport, pendingScoring]);

  const retryReport = () => {
    reportReadyPollAttempts.current = 0;
    setError("");
    setPendingScoring(false);
    void loadReport();
  };

  useEffect(() => {
    if (!report) return;
    void getReportQuestions(report.id, page)
      .then(setQuestions)
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
      setNotice(`正在生成 ${exportLabels[format]}`);
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
        description={pendingScoring ? "检测已结束，正在完成评分并生成报告" : "正在加载报告"}
      />
    );
  }

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Typography.Title level={2}>GEO 检测报告</Typography.Title>
        {error && <Alert type="error" showIcon title={error} />}
        {!report && props.detectionId && error && (
          <Space wrap>
            <Button href={`/geo/detections/${props.detectionId}`}>返回检测结果</Button>
            <Button type="primary" onClick={retryReport}>
              重新检查报告
            </Button>
          </Space>
        )}
        {notice && <Alert type="success" showIcon title={notice} />}
        {pendingScoring && (
          <Alert type="info" showIcon title="检测已结束，报告评分完成后即可查看正式报告" />
        )}
        {report && (
          <>
            <Row gutter={[16, 16]}>
              <Col xs={24} md={12}>
                <Card>
                  <Statistic
                    title="GEO 综合得分"
                    value={report.summary.geo.score || "-"}
                    suffix={report.summary.geo.grade}
                  />
                </Card>
              </Col>
              <Col xs={24} md={12}>
                <Card>
                  <Statistic
                    title="品牌认知与口碑"
                    value={report.summary.brand_reputation.score || "-"}
                    suffix={report.summary.brand_reputation.grade}
                  />
                </Card>
              </Col>
            </Row>

            <Card title="六维评分">
              <Row gutter={[16, 16]}>
                {Object.entries(report.summary.dimensions).map(([key, value]) => (
                  <Col xs={12} md={8} lg={4} key={key}>
                    <Statistic title={dimensionLabels[key] || "其他指标"} value={value || "-"} />
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
                      title={aiModelDisplayName(model.model_key)}
                      description={`成功 ${model.successful_calls}/${model.planned_calls}`}
                    />
                    <Space wrap>
                      <Tag color="blue">GEO {model.geo?.score || "-"}</Tag>
                      <Tag>口碑 {model.brand_reputation?.score || "-"}</Tag>
                      <Tag>{reportStatusLabel(model.geo?.status || model.status)}</Tag>
                    </Space>
                  </List.Item>
                )}
              />
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
                                <Typography.Text strong>
                                  {aiModelDisplayName(result.model_key)}
                                </Typography.Text>
                                <Tag>{reportStatusLabel(result.status)}</Tag>
                                {result.score?.total && (
                                  <Tag color="blue">单题 {result.score.total}</Tag>
                                )}
                              </Space>
                              <Typography.Paragraph>
                                {result.snippet || "本次未获得有效回答"}
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

            <Card title="导出与复测">
              <Space orientation="vertical" style={{ width: "100%" }}>
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
                  快速复测沿用原报告的问题和检测模型（{baselineModels}
                  ），并采用当前主体资料与评分口径；若原模型不可用，将明确提示且不会自动替换。
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
            <ReportSharing reportId={report.id} subjectId={report.subject_id} />
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
            title="使用当前可选的问题和模型创建一次独立复测；完成后系统会判断能否与原报告正式对比。"
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
