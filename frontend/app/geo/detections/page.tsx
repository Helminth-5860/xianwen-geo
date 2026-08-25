"use client";

import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  RadarChartOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Checkbox, Empty, Space, Spin, Tag, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  createDetection,
  estimateDetection,
  getDetectionHistory,
  type GeoDetectionEstimate,
  type GeoDetectionJob,
} from "@/lib/geo-detection-client";
import { getDetectionOptions, type DetectionOptions } from "@/lib/geo-report-client";
import {
  getCurrentQuestionBank,
  type QuestionBankVersion,
  type QuestionBankVersionItem,
} from "@/lib/question-bank-client";

const { Paragraph, Text, Title } = Typography;

export default function GeoDetectionIndexPage() {
  const router = useRouter();
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const [options, setOptions] = useState<DetectionOptions | null>(null);
  const [questionBank, setQuestionBank] = useState<QuestionBankVersion | null>(null);
  const [history, setHistory] = useState<GeoDetectionJob[]>([]);
  const [selectedQuestions, setSelectedQuestions] = useState<string[]>([]);
  const [selectedModels, setSelectedModels] = useState<string[]>([]);
  const [estimate, setEstimate] = useState<GeoDetectionEstimate | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;
    if (subjectLoading) return () => undefined;
    if (!subject) return () => undefined;
    void (async () => {
      const [optionResult, questionResult, historyResult] = await Promise.allSettled([
        getDetectionOptions(subject.id),
        getCurrentQuestionBank(subject.id),
        getDetectionHistory(subject.id),
      ]);
      if (!current) return;

      if (historyResult.status === "fulfilled") {
        setHistory(
          [...historyResult.value.items].sort(
            (left, right) =>
              new Date(right.created_at).getTime() - new Date(left.created_at).getTime(),
          ),
        );
      }

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
    })()
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
    };
  }, [subject, subjectLoading]);

  const questions = useMemo<QuestionBankVersionItem[]>(
    () =>
      [...(questionBank?.items ?? [])].sort((left, right) => left.sort_order - right.sort_order),
    [questionBank],
  );

  const toggleQuestion = (questionId: string, checked: boolean) => {
    setEstimate(null);
    setSelectedQuestions((current) => {
      if (!checked) return current.filter((id) => id !== questionId);
      if (!options || current.length >= options.max_questions_per_detection) return current;
      return [...current, questionId];
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

  const runEstimate = async () => {
    if (!subject || selectedQuestions.length === 0 || selectedModels.length === 0) return;
    setBusy(true);
    setError("");
    try {
      setEstimate(await estimateDetection(subject.id, selectedQuestions, selectedModels));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const startDetection = async () => {
    if (!subject || selectedQuestions.length === 0 || selectedModels.length === 0) return;
    setBusy(true);
    setError("");
    try {
      const currentEstimate =
        estimate ?? (await estimateDetection(subject.id, selectedQuestions, selectedModels));
      setEstimate(currentEstimate);
      if (!currentEstimate.can_submit) return;
      const created = await createDetection(
        subject.id,
        selectedQuestions,
        selectedModels,
        crypto.randomUUID(),
      );
      router.push(`/geo/detections/${created.detection_id}`);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  if (subjectLoading || (subject && loading))
    return <Spin fullscreen description="正在加载 AI 可见度检测" />;

  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">GEO DETECTION</Text>
          <Title level={2}>AI 可见度检测</Title>
          <Paragraph type="secondary">
            用正式问题库在已配置的 AI 模型上执行真实检测，建立品牌在生成式搜索中的可见度基线。
          </Paragraph>
        </div>
        <Button href="/workspace">返回 GEO 总览</Button>
      </section>

      {error && <Alert type="warning" showIcon message={error} />}

      {!subject ? (
        <Card>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              进入主体与知识
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
            <Space wrap>
              {questionBank && <Tag color="blue">问题库 v{questionBank.version_no}</Tag>}
              {options && <Tag>检测点余额 {options.available_detection_points}</Tag>}
            </Space>
          </section>

          <section className="geo-dashboard__main-grid">
            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Card title="1. 选择检测问题">
                {!questionBank ? (
                  <Space direction="vertical">
                    <Text type="secondary">还没有正式问题库。</Text>
                    <Button href={`/subjects/${subject.id}/keywords`}>建立关键词与问题库</Button>
                  </Space>
                ) : (
                  <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    <Text type="secondary">
                      已选择 {selectedQuestions.length} /{" "}
                      {options?.max_questions_per_detection ?? "—"} 个问题
                    </Text>
                    {questions.map((question) => (
                      <label key={question.id} className="geo-selection-row">
                        <Checkbox
                          checked={selectedQuestions.includes(question.id)}
                          disabled={
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
                            {question.question_type === "brand_directed"
                              ? "品牌指向型"
                              : "自然探索型"}
                            {!question.participates_in_scoring ? " · 不参与检测" : ""}
                          </Text>
                        </span>
                      </label>
                    ))}
                  </Space>
                )}
              </Card>

              <Card title="2. 选择 AI 模型">
                {!options ? (
                  <Text type="secondary">检测条件尚未就绪。</Text>
                ) : (
                  <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    <Text type="secondary">
                      已选择 {selectedModels.length} / {options.max_models_per_detection} 个模型
                    </Text>
                    {options.models.map((model) => (
                      <label key={model.id} className="geo-selection-row">
                        <Checkbox
                          checked={selectedModels.includes(model.id)}
                          disabled={
                            !model.configured ||
                            (!selectedModels.includes(model.id) &&
                              selectedModels.length >= options.max_models_per_detection)
                          }
                          onChange={(event) => toggleModel(model.id, event.target.checked)}
                        />
                        <span>
                          <Text>{model.display_name}</Text>
                          <Text type="secondary">
                            {model.configured ? "已配置" : "当前不可用"}
                            {model.selected_by_default ? " · 默认模型" : ""}
                          </Text>
                        </span>
                      </label>
                    ))}
                  </Space>
                )}
              </Card>
            </Space>

            <Space direction="vertical" size="middle" style={{ width: "100%" }}>
              <Card title="检测预估">
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
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
                      <Text type="secondary">预计检测点</Text>
                      <Text strong>
                        {estimate?.required_detection_points ??
                          selectedQuestions.length * selectedModels.length}
                      </Text>
                    </span>
                    <span>
                      <Text type="secondary">可用检测点</Text>
                      <Text strong>
                        {estimate?.available_detection_points ??
                          options?.available_detection_points ??
                          "—"}
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
                          ? `将执行 ${estimate.question_count} × ${estimate.model_count} 个检测调用。`
                          : "请检查检测点余额或当前并发任务数量。"
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
                      icon={<RadarChartOutlined />}
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

              <Card title="最近检测">
                {history.length === 0 ? (
                  <Text type="secondary">暂无检测记录。</Text>
                ) : (
                  <Space direction="vertical" size="small" style={{ width: "100%" }}>
                    {history.slice(0, 6).map((job) => (
                      <a key={job.id} href={`/geo/detections/${job.id}`} className="geo-report-row">
                        <span>
                          <Space>
                            {job.status === "succeeded" ? (
                              <CheckCircleOutlined />
                            ) : (
                              <ClockCircleOutlined />
                            )}
                            <Text strong>{job.status}</Text>
                            <Tag>{job.planned_detection_points} 检测点</Tag>
                          </Space>
                          <Text type="secondary">
                            {job.progress_percent}% ·{" "}
                            {new Date(job.created_at).toLocaleString("zh-CN")}
                          </Text>
                        </span>
                        <ArrowRightOutlined />
                      </a>
                    ))}
                  </Space>
                )}
              </Card>
            </Space>
          </section>
        </>
      )}
    </main>
  );
}
