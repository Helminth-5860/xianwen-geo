"use client";

import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  DeleteOutlined,
  RadarChartOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Checkbox,
  ConfigProvider,
  Empty,
  Modal,
  Pagination,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import zhCN from "antd/locale/zh_CN";
import Image from "next/image";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { aiModelPresentation } from "@/lib/ai-model-presentation";
import { userMessage } from "@/lib/auth-client";
import {
  DETECTION_QUESTION_PAGE_SIZE,
  DETECTION_RESULT_PAGE_SIZE,
} from "@/lib/detection-ui-constants";
import {
  createDetection,
  estimateDetection,
  getDetectionHistory,
  removeDetectionResult,
  terminalDetectionStatuses,
  type GeoDetectionEstimate,
  type GeoDetectionJob,
} from "@/lib/geo-detection-client";
import { getDetectionOptions, type DetectionOptions } from "@/lib/geo-report-client";
import {
  getCurrentQuestionBank,
  type QuestionBankVersion,
  type QuestionBankVersionItem,
} from "@/lib/question-bank-client";
import type { SubjectSummary } from "@/lib/subjects-client";

const { Paragraph, Text, Title } = Typography;

const detectionStatusLabels: Readonly<Record<GeoDetectionJob["status"], string>> = {
  queued: "等待检测",
  running: "检测中",
  partial: "部分完成",
  succeeded: "已完成",
  failed: "未完成",
  cancelled: "已取消",
};

const detectionStatusColors: Readonly<Record<GeoDetectionJob["status"], string>> = {
  queued: "default",
  running: "processing",
  partial: "warning",
  succeeded: "success",
  failed: "error",
  cancelled: "default",
};

function ModelLogo({ modelKey, displayName }: Readonly<{ modelKey: string; displayName: string }>) {
  const presentation = aiModelPresentation(modelKey, displayName);
  if (!presentation.logoPath) {
    return (
      <span className="geo-model-choice__fallback" aria-hidden="true">
        {presentation.name.trim().slice(0, 1)}
      </span>
    );
  }
  return (
    <Image
      className="geo-model-choice__logo"
      src={presentation.logoPath}
      alt={`${presentation.name}标识`}
      width={44}
      height={44}
    />
  );
}

export default function GeoDetectionIndexPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();

  if (subjectLoading) return <Spin fullscreen description="正在加载 AI 可见度检测" />;
  if (!subject) {
    return (
      <main className="geo-dashboard geo-detection-index">
        <section className="geo-dashboard__header">
          <div>
            <Text type="secondary">GEO 检测</Text>
            <Title level={2}>AI 可见度检测</Title>
            <Paragraph type="secondary">
              勾选正式问题和目标 AI 模型，检测品牌在生成式搜索中的可见度表现。
            </Paragraph>
          </div>
          <Button href="/workspace">返回 GEO 总览</Button>
        </section>
        <Card>
          <Empty description="请先绑定主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </Card>
      </main>
    );
  }

  return (
    <ConfigProvider locale={zhCN}>
      <SubjectDetectionPage key={subject.id} subject={subject} />
    </ConfigProvider>
  );
}

function SubjectDetectionPage({ subject }: Readonly<{ subject: SubjectSummary }>) {
  const router = useRouter();
  const mountedRef = useRef(true);
  const subjectId = subject.id;
  const [options, setOptions] = useState<DetectionOptions | null>(null);
  const [questionBank, setQuestionBank] = useState<QuestionBankVersion | null>(null);
  const [history, setHistory] = useState<GeoDetectionJob[]>([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [selectedQuestions, setSelectedQuestions] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [selectedResults, setSelectedResults] = useState<string[]>([]);
  const [estimate, setEstimate] = useState<GeoDetectionEstimate | null>(null);
  const [questionPage, setQuestionPage] = useState(1);
  const [resultPage, setResultPage] = useState(1);
  const [historyReloadKey, setHistoryReloadKey] = useState(0);
  const [pendingDeletionIds, setPendingDeletionIds] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  useEffect(() => {
    let current = true;
    void Promise.allSettled([getDetectionOptions(subjectId), getCurrentQuestionBank(subjectId)])
      .then(([optionResult, questionResult]) => {
        if (!current) return;
        if (questionResult.status === "fulfilled") setQuestionBank(questionResult.value);
        if (optionResult.status === "fulfilled") setOptions(optionResult.value);

        if (questionResult.status === "fulfilled" && optionResult.status === "fulfilled") {
          const scoringQuestions = (questionResult.value.items ?? []).filter(
            (item) => item.participates_in_scoring,
          );
          setSelectedQuestions(
            scoringQuestions
              .slice(0, optionResult.value.max_questions_per_detection)
              .map((item) => item.id),
          );

          const configuredModels = optionResult.value.models.filter((model) => model.configured);
          const defaults = configuredModels.filter((model) => model.selected_by_default);
          const initialModels = defaults.length > 0 ? defaults : configuredModels;
          setSelectedModels(
            initialModels
              .slice(0, optionResult.value.max_models_per_detection)
              .map((model) => model.id),
          );
        }

        if (optionResult.status === "rejected") setError(userMessage(optionResult.reason));
        else if (questionResult.status === "rejected") {
          setError("当前主体还没有可用于检测的正式问题库，请先完成关键词与问题流程。");
        }
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
    };
  }, [subjectId]);

  useEffect(() => {
    let current = true;
    void getDetectionHistory(subjectId, resultPage)
      .then((result) => {
        if (!current) return;
        const ownedItems = result.items
          .filter((item) => item.subject_id === subjectId)
          .sort(
            (left, right) =>
              new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
          );
        if (result.pagination) {
          setHistory(ownedItems.slice(0, DETECTION_RESULT_PAGE_SIZE));
          setHistoryTotal(result.pagination.count);
        } else {
          const start = (resultPage - 1) * DETECTION_RESULT_PAGE_SIZE;
          setHistory(ownedItems.slice(start, start + DETECTION_RESULT_PAGE_SIZE));
          setHistoryTotal(ownedItems.length);
        }
      })
      .catch((reason) => {
        if (current) {
          setHistory([]);
          setHistoryTotal(0);
          setError(userMessage(reason));
        }
      })
      .finally(() => {
        if (current) setHistoryLoading(false);
      });

    return () => {
      current = false;
    };
  }, [historyReloadKey, resultPage, subjectId]);

  const questions = useMemo<QuestionBankVersionItem[]>(
    () =>
      [...(questionBank?.items ?? [])].sort((left, right) => left.sort_order - right.sort_order),
    [questionBank],
  );
  const displayedHistory = history;
  const displayedHistoryTotal = historyTotal;
  const visibleQuestions = useMemo(() => {
    const start = (questionPage - 1) * DETECTION_QUESTION_PAGE_SIZE;
    return questions.slice(start, start + DETECTION_QUESTION_PAGE_SIZE);
  }, [questionPage, questions]);
  const pageSelectableQuestionIds = useMemo(
    () => visibleQuestions.filter((item) => item.participates_in_scoring).map((item) => item.id),
    [visibleQuestions],
  );
  const pageSelectedQuestionCount = pageSelectableQuestionIds.filter((id) =>
    selectedQuestions.includes(id),
  ).length;
  const selectableResultIds = useMemo(
    () =>
      displayedHistory
        .filter((job) => terminalDetectionStatuses.has(job.status))
        .map((job) => job.id),
    [displayedHistory],
  );
  const pageSelectedResultCount = selectableResultIds.filter((id) =>
    selectedResults.includes(id),
  ).length;

  const toggleQuestion = (questionId: string, checked: boolean) => {
    setEstimate(null);
    setSelectedQuestions((current) => {
      if (!checked) return current.filter((id) => id !== questionId);
      if (!options || current.length >= options.max_questions_per_detection) return current;
      return [...current, questionId];
    });
  };

  const toggleCurrentQuestionPage = (checked: boolean) => {
    setEstimate(null);
    setSelectedQuestions((current) => {
      const pageIds = new Set(pageSelectableQuestionIds);
      if (!checked) return current.filter((id) => !pageIds.has(id));
      if (!options) return current;
      const additions = pageSelectableQuestionIds.filter((id) => !current.includes(id));
      return [...current, ...additions].slice(0, options.max_questions_per_detection);
    });
  };

  const toggleModel = (modelId: string, checked: boolean) => {
    setEstimate(null);
    setSelectedModels((current) => {
      if (!checked) return current.filter((id) => id !== modelId);
      if (!options || current.length >= options.max_models_per_detection) return current;
      return [...current, modelId];
    });
  };

  const selectAllAvailableModels = () => {
    if (!options) return;
    setEstimate(null);
    setSelectedModels(
      options.models
        .filter((model) => model.configured)
        .slice(0, options.max_models_per_detection)
        .map((model) => model.id),
    );
  };

  const runEstimate = async () => {
    if (!subjectId || selectedQuestions.length === 0 || selectedModels.length === 0) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      setEstimate(await estimateDetection(subjectId, selectedQuestions, selectedModels));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const startDetection = async () => {
    if (!subjectId || selectedQuestions.length === 0 || selectedModels.length === 0) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const currentEstimate =
        estimate ?? (await estimateDetection(subjectId, selectedQuestions, selectedModels));
      setEstimate(currentEstimate);
      if (!currentEstimate.can_submit) return;
      const created = await createDetection(
        subjectId,
        selectedQuestions,
        selectedModels,
        crypto.randomUUID(),
      );
      if (mountedRef.current) router.push(`/geo/detections/${created.detection_id}`);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const confirmDeletion = async () => {
    if (pendingDeletionIds.length === 0) return;
    setDeleting(true);
    setError("");
    setNotice("");
    const ids = [...pendingDeletionIds];
    const results = await Promise.allSettled(
      ids.map((detectionId) => removeDetectionResult(subjectId, detectionId)),
    );
    const removedIds = ids.filter((_, index) => results[index]?.status === "fulfilled");
    const failed = results.length - removedIds.length;
    if (removedIds.length > 0) {
      setNotice(`已删除 ${removedIds.length} 条检测结果。`);
      setSelectedResults((current) => current.filter((id) => !removedIds.includes(id)));
      const nextTotal = Math.max(0, displayedHistoryTotal - removedIds.length);
      const lastPage = Math.max(1, Math.ceil(nextTotal / DETECTION_RESULT_PAGE_SIZE));
      setHistoryLoading(true);
      if (resultPage > lastPage) setResultPage(lastPage);
      else setHistoryReloadKey((current) => current + 1);
    }
    if (failed > 0) setError("部分检测结果暂未删除，请稍后重新尝试。");
    setPendingDeletionIds([]);
    setDeleting(false);
  };

  if (loading) return <Spin fullscreen description="正在加载 AI 可见度检测" />;

  return (
    <main className="geo-dashboard geo-detection-index">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">GEO 检测</Text>
          <Title level={2}>AI 可见度检测</Title>
          <Paragraph type="secondary">
            勾选正式问题和目标 AI 模型，检测品牌在生成式搜索中的可见度表现。
          </Paragraph>
        </div>
        <Button href="/workspace">返回 GEO 总览</Button>
      </section>

      {error && <Alert type="warning" showIcon message={error} />}
      {notice && <Alert type="success" showIcon message={notice} />}

      <section className="geo-dashboard__subject-bar">
        <div>
          <Text type="secondary">当前主体</Text>
          <Title level={3}>{subject.official_name || subject.subject_type.name}</Title>
        </div>
        <Space wrap>
          {questionBank && <Tag color="blue">问题库已就绪</Tag>}
          {options && <Tag>检测剩余 {options.available_detection_runs} 次</Tag>}
        </Space>
      </section>

      <section className="geo-detection-planner">
        <Card title="1. 选择检测问题" className="geo-detection-planner__questions">
          {!questionBank ? (
            <Space orientation="vertical">
              <Text type="secondary">还没有正式问题库。</Text>
              <Button href={`/subjects/${subject.id}/keywords`}>建立关键词与问题库</Button>
            </Space>
          ) : (
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <div className="geo-detection-list-toolbar">
                <Space wrap>
                  <Checkbox
                    checked={
                      pageSelectableQuestionIds.length > 0 &&
                      pageSelectedQuestionCount === pageSelectableQuestionIds.length
                    }
                    indeterminate={
                      pageSelectedQuestionCount > 0 &&
                      pageSelectedQuestionCount < pageSelectableQuestionIds.length
                    }
                    disabled={busy}
                    onChange={(event) => toggleCurrentQuestionPage(event.target.checked)}
                  >
                    全选本页
                  </Checkbox>
                  <Button
                    type="link"
                    disabled={busy || selectedQuestions.length === 0}
                    onClick={() => {
                      setEstimate(null);
                      setSelectedQuestions([]);
                    }}
                  >
                    清空已选
                  </Button>
                </Space>
                <Text type="secondary">
                  已选择 {selectedQuestions.length} / {options?.max_questions_per_detection ?? "—"}{" "}
                  个问题
                </Text>
              </div>
              <div className="geo-detection-question-list">
                {visibleQuestions.map((question) => (
                  <label key={question.id} className="geo-selection-row">
                    <Checkbox
                      aria-label={`选择问题：${question.text}`}
                      checked={selectedQuestions.includes(question.id)}
                      disabled={
                        busy ||
                        !question.participates_in_scoring ||
                        (!selectedQuestions.includes(question.id) &&
                          Boolean(
                            options &&
                            selectedQuestions.length >= options.max_questions_per_detection,
                          ))
                      }
                      onChange={(event) => toggleQuestion(question.id, event.target.checked)}
                    />
                    <span>
                      <Text>{question.text}</Text>
                      <Text type="secondary">
                        {question.question_type === "brand_directed" ? "品牌指向型" : "自然探索型"}
                        {!question.participates_in_scoring ? " · 不参与检测" : ""}
                      </Text>
                    </span>
                  </label>
                ))}
              </div>
              {questions.length > DETECTION_QUESTION_PAGE_SIZE && (
                <Pagination
                  aria-label="检测问题分页"
                  current={questionPage}
                  pageSize={DETECTION_QUESTION_PAGE_SIZE}
                  total={questions.length}
                  showSizeChanger={false}
                  showTotal={(total) => `共 ${total} 个问题`}
                  onChange={setQuestionPage}
                />
              )}
            </Space>
          )}
        </Card>

        <Space orientation="vertical" size="middle" className="geo-detection-planner__sidebar">
          <Card title="2. 选择 AI 模型">
            {!options ? (
              <Text type="secondary">检测条件尚未就绪。</Text>
            ) : (
              <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                <div className="geo-detection-list-toolbar">
                  <Space wrap>
                    <Button type="link" disabled={busy} onClick={selectAllAvailableModels}>
                      选择全部可用模型
                    </Button>
                    <Button
                      type="link"
                      disabled={busy || selectedModels.length === 0}
                      onClick={() => {
                        setEstimate(null);
                        setSelectedModels([]);
                      }}
                    >
                      清空已选
                    </Button>
                  </Space>
                  <Text type="secondary">
                    已选择 {selectedModels.length} / {options.max_models_per_detection}
                  </Text>
                </div>
                <div className="geo-model-choice-grid">
                  {options.models.map((model) => {
                    const presentation = aiModelPresentation(model.model_key, model.display_name);
                    return (
                      <label key={model.id} className="geo-model-choice">
                        <Checkbox
                          aria-label={`选择模型：${presentation.name}`}
                          checked={selectedModels.includes(model.id)}
                          disabled={
                            busy ||
                            !model.configured ||
                            (!selectedModels.includes(model.id) &&
                              selectedModels.length >= options.max_models_per_detection)
                          }
                          onChange={(event) => toggleModel(model.id, event.target.checked)}
                        />
                        <ModelLogo modelKey={model.model_key} displayName={model.display_name} />
                        <span className="geo-model-choice__content">
                          <Text strong>{presentation.name}</Text>
                          <Text type="secondary">
                            {model.configured ? "可用于检测" : "当前不可用"}
                          </Text>
                        </span>
                      </label>
                    );
                  })}
                </div>
              </Space>
            )}
          </Card>

          <Card title="3. 检测预估">
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <div className="geo-estimate-grid">
                <span>
                  <Text type="secondary">问题</Text>
                  <Text strong>{selectedQuestions.length}</Text>
                </span>
                <span>
                  <Text type="secondary">模型</Text>
                  <Text strong>{selectedModels.length}</Text>
                </span>
                <span>
                  <Text type="secondary">本次使用</Text>
                  <Text strong>{estimate?.required_detection_runs ?? 1} 次</Text>
                </span>
                <span>
                  <Text type="secondary">当前剩余</Text>
                  <Text strong>
                    {estimate?.available_detection_runs ??
                      options?.available_detection_runs ??
                      "—"} 次
                  </Text>
                </span>
              </div>
              {estimate && (
                <Alert
                  type={estimate.can_submit ? "success" : "warning"}
                  showIcon
                  message={estimate.can_submit ? "检测条件已满足" : "当前条件无法提交"}
                  description={
                    estimate.can_submit
                      ? `本次将使用1次GEO检测额度，共执行 ${estimate.question_count} 个问题 × ${estimate.model_count} 个模型。`
                      : "请检查检测次数余额，或等待正在进行的检测结束。"
                  }
                />
              )}
              <Space wrap>
                <Button
                  loading={busy}
                  disabled={selectedQuestions.length === 0 || selectedModels.length === 0}
                  onClick={() => void runEstimate()}
                >
                  计算检测用量
                </Button>
                <Button
                  type="primary"
                  icon={<RadarChartOutlined aria-hidden="true" />}
                  loading={busy}
                  disabled={
                    !options?.can_start_job ||
                    selectedQuestions.length === 0 ||
                    selectedModels.length === 0 ||
                    Boolean(estimate && !estimate.can_submit)
                  }
                  onClick={() => void startDetection()}
                >
                  开始检测
                </Button>
              </Space>
            </Space>
          </Card>
        </Space>
      </section>

      <Card title="检测结果" className="geo-detection-results">
        <Spin spinning={historyLoading}>
          {displayedHistoryTotal === 0 && !historyLoading ? (
            <Empty description="还没有检测结果，完成检测后会显示在这里。" />
          ) : (
            <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
              <div className="geo-detection-list-toolbar">
                <Space wrap>
                  <Checkbox
                    checked={
                      selectableResultIds.length > 0 &&
                      pageSelectedResultCount === selectableResultIds.length
                    }
                    indeterminate={
                      pageSelectedResultCount > 0 &&
                      pageSelectedResultCount < selectableResultIds.length
                    }
                    disabled={selectableResultIds.length === 0}
                    onChange={(event) => {
                      setSelectedResults(event.target.checked ? selectableResultIds : []);
                    }}
                  >
                    全选本页已完成结果
                  </Checkbox>
                  <Button
                    danger
                    icon={<DeleteOutlined aria-hidden="true" />}
                    disabled={selectedResults.length === 0}
                    onClick={() => setPendingDeletionIds(selectedResults)}
                  >
                    删除所选
                  </Button>
                </Space>
                <Text type="secondary">共 {displayedHistoryTotal} 条检测结果</Text>
              </div>

              <div className="geo-detection-result-list">
                {displayedHistory.map((job) => {
                  const terminal = terminalDetectionStatuses.has(job.status);
                  return (
                    <div key={job.id} className="geo-detection-result-row">
                      <Checkbox
                        aria-label={`选择检测结果：${new Date(job.created_at).toLocaleString("zh-CN")}`}
                        checked={selectedResults.includes(job.id)}
                        disabled={!terminal}
                        onChange={(event) => {
                          setSelectedResults((current) =>
                            event.target.checked
                              ? [...current, job.id]
                              : current.filter((id) => id !== job.id),
                          );
                        }}
                      />
                      <span className="geo-detection-result-row__content">
                        <Space wrap>
                          {job.status === "succeeded" ? (
                            <CheckCircleOutlined aria-hidden="true" />
                          ) : (
                            <ClockCircleOutlined aria-hidden="true" />
                          )}
                          <Tag color={detectionStatusColors[job.status]}>
                            {detectionStatusLabels[job.status]}
                          </Tag>
                          <Text>{job.planned_question_count} 个问题</Text>
                          <Text>{job.planned_model_count} 个模型</Text>
                          <Text>{job.planned_question_count} 个问题 × {job.planned_model_count} 个模型</Text>
                        </Space>
                        <Text type="secondary">
                          完成进度 {job.progress_percent}% ·{" "}
                          {new Date(job.created_at).toLocaleString("zh-CN")}
                        </Text>
                      </span>
                      <Space wrap className="geo-detection-result-row__actions">
                        <Button
                          href={
                            terminal
                              ? `/geo/detections/${job.id}/report`
                              : `/geo/detections/${job.id}`
                          }
                        >
                          {terminal ? "查看结果" : "查看进度"}
                        </Button>
                        {terminal && (
                          <Button danger onClick={() => setPendingDeletionIds([job.id])}>
                            删除
                          </Button>
                        )}
                      </Space>
                    </div>
                  );
                })}
              </div>

              {displayedHistoryTotal > DETECTION_RESULT_PAGE_SIZE && (
                <Pagination
                  aria-label="检测结果分页"
                  current={resultPage}
                  pageSize={DETECTION_RESULT_PAGE_SIZE}
                  total={displayedHistoryTotal}
                  showSizeChanger={false}
                  showTotal={(total) => `共 ${total} 条结果`}
                  onChange={(page) => {
                    setSelectedResults([]);
                    setHistoryLoading(true);
                    setResultPage(page);
                  }}
                />
              )}
            </Space>
          )}
        </Spin>
      </Card>

      <Modal
        open={pendingDeletionIds.length > 0}
        title="确认删除检测结果"
        okText="确认删除"
        cancelText="取消"
        confirmLoading={deleting}
        okButtonProps={{ danger: true }}
        onOk={() => void confirmDeletion()}
        onCancel={() => {
          if (!deleting) setPendingDeletionIds([]);
        }}
      >
        <Paragraph>
          将从检测结果列表中删除 {pendingDeletionIds.length}{" "}
          条记录。已形成的统计与报告仍会安全保留。
        </Paragraph>
      </Modal>
    </main>
  );
}
