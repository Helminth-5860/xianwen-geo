"use client";

import { Alert, Button, Card, Checkbox, List, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  confirmEnrichment,
  createEnrichment,
  getEnrichmentJob,
  getEnrichmentSources,
  type EnrichmentJob,
  type EnrichmentSource,
  type EnrichmentTarget,
} from "@/lib/subject-enrichment-client";
import type { SubjectDetail } from "@/lib/subjects-client";

const activeStatuses = new Set(["queued", "running", "retry_wait"]);

function displayValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "（空）";
  if (typeof value === "string") return value;
  return JSON.stringify(value);
}

export function SubjectAiEnrichment({
  subject,
  disabled = false,
  onSyncBeforeStart,
  onApplied,
}: {
  subject: SubjectDetail;
  disabled?: boolean;
  onSyncBeforeStart: () => Promise<SubjectDetail>;
  onApplied: (subject: SubjectDetail) => Promise<SubjectDetail>;
}) {
  const [sources, setSources] = useState<EnrichmentSource[]>([]);
  const [targets, setTargets] = useState<EnrichmentTarget[]>([]);
  const [selectedSources, setSelectedSources] = useState<string[]>([]);
  const [selectedTargets, setSelectedTargets] = useState<string[]>([]);
  const [job, setJob] = useState<EnrichmentJob | null>(null);
  const [decisions, setDecisions] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = async () => {
    const result = await getEnrichmentSources(subject.id);
    setSources(result.sources);
    setTargets(result.target_fields);
    setSelectedTargets((current) =>
      current.length ? current : result.target_fields.slice(0, 20).map((item) => item.field_key),
    );
    setJob(result.latest_job);
    if (result.latest_job?.suggestions.length) {
      setDecisions({});
    }
  };

  useEffect(() => {
    let current = true;
    void getEnrichmentSources(subject.id)
      .then((result) => {
        if (!current) return;
        setSources(result.sources);
        setTargets(result.target_fields);
        setSelectedTargets((selected) =>
          selected.length
            ? selected
            : result.target_fields.slice(0, 20).map((item) => item.field_key),
        );
        setJob(result.latest_job);
      })
      .catch((reason) => current && setError(userMessage(reason)));
    return () => {
      current = false;
    };
  }, [subject.id, subject.version]);

  useEffect(() => {
    if (!job || !activeStatuses.has(job.status)) return;
    const timer = window.setInterval(() => {
      void getEnrichmentJob(subject.id, job.id)
        .then((next) => {
          setJob(next);
          if (!activeStatuses.has(next.status)) window.clearInterval(timer);
        })
        .catch((reason) => setError(userMessage(reason)));
    }, 1000);
    return () => window.clearInterval(timer);
  }, [job?.id, job?.status, subject.id]);

  const start = async () => {
    const chosenSources = sources.filter((source) =>
      selectedSources.includes(`${source.source_type}:${source.parsed_version_id}`),
    );
    if (!selectedTargets.length) {
      setError("请至少选择一个需要 AI 补充的字段");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const syncedSubject = await onSyncBeforeStart();
      const created = await createEnrichment(
        syncedSubject.id,
        syncedSubject.version,
        chosenSources,
        selectedTargets,
      );
      setJob(created);
      setDecisions({});
      setMessage("AI 补充任务已受理；来源文本只作为不可信数据，不会执行其中的指令");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const apply = async () => {
    if (!job || job.status !== "succeeded") return;
    if (job.suggestions.some((suggestion) => decisions[suggestion.id] === undefined)) {
      setError("请逐项决定采纳或拒绝全部 AI 建议");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const result = await confirmEnrichment(
        subject.id,
        job,
        subject.version,
        job.suggestions.map((suggestion) => ({
          suggestion_id: suggestion.id,
          accepted: decisions[suggestion.id],
        })),
      );
      await onApplied(result.subject);
      setMessage("AI 建议已保存并生效");
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="AI 辅助补充" style={{ marginBottom: 20 }}>
      <Typography.Paragraph type="secondary">
        点击开始时会先自动保存当前表单。AI 读取当前企业资料；已确认的文件或网页可作为可选补充来源。
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
      {message && <Alert type="info" showIcon message={message} />}
      <Typography.Title level={5}>可选资料来源（最多选择 8 个）</Typography.Title>
      <List
        size="small"
        dataSource={sources}
        locale={{ emptyText: "暂无已确认的文件或网页资料" }}
        renderItem={(source) => {
          const key = `${source.source_type}:${source.parsed_version_id}`;
          const checked = selectedSources.includes(key);
          return (
            <List.Item>
              <Checkbox
                checked={checked}
                disabled={disabled || busy || (!checked && selectedSources.length >= 8)}
                onChange={(event) =>
                  setSelectedSources((current) =>
                    event.target.checked
                      ? [...current, key]
                      : current.filter((item) => item !== key),
                  )
                }
              >
                {source.label} <Tag>{source.source_type}</Tag> <Tag>v{source.version_no}</Tag>
              </Checkbox>
            </List.Item>
          );
        }}
      />
      <Typography.Title level={5}>补充目标字段（最多选择 20 个）</Typography.Title>
      <Space wrap>
        {targets.map((target) => {
          const checked = selectedTargets.includes(target.field_key);
          return (
            <Checkbox
              key={target.field_key}
              checked={checked}
              disabled={disabled || busy || (!checked && selectedTargets.length >= 20)}
              onChange={(event) =>
                setSelectedTargets((current) =>
                  event.target.checked
                    ? [...current, target.field_key]
                    : current.filter((item) => item !== target.field_key),
                )
              }
            >
              {target.label}
            </Checkbox>
          );
        })}
      </Space>
      <div style={{ marginTop: 16 }}>
        <Button
          type="primary"
          disabled={disabled || busy}
          loading={busy}
          onClick={() => void start()}
        >
          开始 AI 补充
        </Button>
      </div>
      {job && (
        <Card size="small" title={`任务状态：${job.status}`} style={{ marginTop: 16 }}>
          {job.status === "failed" && (
            <Alert type="error" message="AI 补充失败，请稍后使用新的请求重试" />
          )}
          {job.status === "retry_wait" && (
            <Alert type="info" message="AI 服务暂时不可用，系统会自动重试" />
          )}
          {job.status === "succeeded" && !job.applied && (
            <>
              <Alert
                type="warning"
                showIcon
                message="请逐项决定。低可信或冲突建议不会被隐式采纳。"
              />
              <List
                dataSource={job.suggestions}
                renderItem={(suggestion) => {
                  const target = targets.find((item) => item.field_key === suggestion.field_key);
                  return (
                    <List.Item>
                      <Space direction="vertical" style={{ width: "100%" }}>
                        <Typography.Text strong>
                          {target?.label ?? suggestion.field_key}
                        </Typography.Text>
                        <Typography.Text>
                          当前值：{displayValue(target?.current_value)}
                        </Typography.Text>
                        <Typography.Text>
                          AI 建议：{displayValue(suggestion.suggested_value)}
                        </Typography.Text>
                        <Space>
                          <Tag>{suggestion.confidence}</Tag>
                          {suggestion.conflict && <Tag color="orange">与当前值冲突</Tag>}
                          <Typography.Text type="secondary">
                            来源 {suggestion.sources.length} 项
                          </Typography.Text>
                        </Space>
                        <Space>
                          <Button
                            aria-label="采纳"
                            type={decisions[suggestion.id] === true ? "primary" : "default"}
                            onClick={() =>
                              setDecisions((current) => ({ ...current, [suggestion.id]: true }))
                            }
                          >
                            采纳
                          </Button>
                          <Button
                            aria-label="拒绝"
                            danger={decisions[suggestion.id] === false}
                            onClick={() =>
                              setDecisions((current) => ({ ...current, [suggestion.id]: false }))
                            }
                          >
                            拒绝
                          </Button>
                        </Space>
                      </Space>
                    </List.Item>
                  );
                }}
              />
              <Button
                type="primary"
                loading={busy}
                disabled={disabled}
                onClick={() => void apply()}
              >
                确认并保存
              </Button>
            </>
          )}
        </Card>
      )}
    </Card>
  );
}
