"use client";

import { Alert, Button, Card, Input, List, Select, Space, Spin, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  askAssistant,
  getAssistantContext,
  type AssistantContext,
  type AssistantMessage,
} from "@/lib/strategy-assistant-client";
import {
  getSubjects,
  setCurrentSubject,
  type SubjectContext,
  type SubjectSummary,
} from "@/lib/subjects-client";

type TranscriptItem = AssistantMessage &
  Readonly<{ id: string; actions?: ReadonlyArray<{ label: string; route: string }> }>;

const isRefusal = (reason: unknown) =>
  reason instanceof AuthApiError &&
  ["ASSISTANT_SCOPE_REFUSED", "ASSISTANT_SECURITY_REFUSED"].includes(reason.code);

export default function AssistantPage() {
  const [subjects, setSubjects] = useState<SubjectSummary[]>();
  const [subjectContext, setSubjectContext] = useState<SubjectContext>();
  const [assistantContext, setAssistantContext] = useState<AssistantContext>();
  const [messages, setMessages] = useState<TranscriptItem[]>([]);
  const [input, setInput] = useState("");
  const [retryPayload, setRetryPayload] = useState<AssistantMessage[]>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [refusal, setRefusal] = useState("");

  const load = async () => {
    const [subjectData, contextData] = await Promise.all([getSubjects(), getAssistantContext()]);
    setSubjects(subjectData.subjects.filter((subject) => subject.status === "active"));
    setSubjectContext(subjectData.context);
    setAssistantContext(contextData);
  };

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load().catch((reason) => setError(userMessage(reason)));
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  const switchSubject = async (subjectId: string) => {
    if (!subjectContext || subjectId === subjectContext.current_subject_id) return;
    setBusy(true);
    try {
      const next = await setCurrentSubject(subjectId, subjectContext.version);
      setSubjectContext(next);
      setMessages([]);
      setRetryPayload(undefined);
      setInput("");
      setError("");
      setRefusal("");
      setAssistantContext(await getAssistantContext());
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const submit = async (payload: AssistantMessage[], appendUser: boolean) => {
    const subjectId = subjectContext?.current_subject_id;
    if (!subjectId) return;
    const userContent = payload.at(-1)?.content ?? "";
    if (appendUser) {
      setMessages((current) => [
        ...current,
        { id: crypto.randomUUID(), role: "user", content: userContent },
      ]);
    }
    setBusy(true);
    setError("");
    setRefusal("");
    try {
      const reply = await askAssistant(subjectId, payload, crypto.randomUUID());
      setMessages((current) => [
        ...current,
        {
          id: reply.usage_event_id,
          role: "assistant",
          content: reply.answer,
          actions: reply.suggested_actions,
        },
      ]);
      setAssistantContext((current) =>
        current ? { ...current, remaining_messages: reply.remaining_messages } : current,
      );
      setRetryPayload(undefined);
    } catch (reason) {
      setRetryPayload(payload);
      if (isRefusal(reason)) setRefusal(userMessage(reason));
      else setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    const content = input.trim();
    if (!content) return;
    const prior = messages.slice(-11).map(({ role, content: itemContent }) => ({
      role,
      content: itemContent,
    }));
    const payload: AssistantMessage[] = [...prior, { role: "user", content }];
    setInput("");
    await submit(payload, true);
  };

  if (!subjects && !error) return <Spin fullscreen description="正在加载显问 AI 助手" />;

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap align="baseline">
          <Typography.Title level={2}>显问 AI 助手</Typography.Title>
          <Tag color="blue">固定 DeepSeek</Tag>
          <Button href="/subjects">主体管理</Button>
        </Space>
        <Alert
          type="info"
          showIcon
          title="聊天记录不保存"
          description="消息只在当前页面会话中临时显示；助手只读取服务端授权的当前主体，不执行检测、策略、文章或资料修改。"
        />
        {error && (
          <Alert
            type="error"
            showIcon
            title={error}
            action={
              retryPayload && (
                <Button size="small" onClick={() => void submit(retryPayload, false)}>
                  重试
                </Button>
              )
            }
          />
        )}
        {refusal && <Alert type="warning" showIcon title="请求已安全拒绝" description={refusal} />}

        <Card title="当前主体">
          <Space wrap>
            <Select
              aria-label="当前主体"
              style={{ minWidth: 260 }}
              loading={busy}
              value={subjectContext?.current_subject_id ?? undefined}
              placeholder="请先选择当前主体"
              onChange={(value) => void switchSubject(value)}
              options={(subjects ?? []).map((subject) => ({
                value: subject.id,
                label: subject.official_name || subject.subject_type.name,
              }))}
            />
            <Typography.Text>
              当前上下文：{assistantContext?.current_subject?.name || "未选择"}
            </Typography.Text>
            <Typography.Text>
              剩余对话次数：{assistantContext?.remaining_messages ?? "当前不可用"}
            </Typography.Text>
          </Space>
        </Card>

        <Card title="本页临时会话">
          <List
            locale={{ emptyText: "可询问当前主体、近期报告和已有改善策略" }}
            dataSource={messages}
            renderItem={(message) => (
              <List.Item>
                <List.Item.Meta
                  title={message.role === "user" ? "你" : "显问助手"}
                  description={
                    <Space orientation="vertical">
                      <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                        {message.content}
                      </Typography.Paragraph>
                      {message.actions?.length ? (
                        <Space wrap>
                          {message.actions.map((action) => (
                            <Link key={`${message.id}-${action.route}`} href={action.route}>
                              {action.label}
                            </Link>
                          ))}
                        </Space>
                      ) : null}
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
          <Space.Compact style={{ width: "100%" }}>
            <Input.TextArea
              aria-label="助手消息"
              autoSize={{ minRows: 2, maxRows: 6 }}
              maxLength={2000}
              value={input}
              disabled={busy || !subjectContext?.current_subject_id}
              placeholder="仅询问当前主体；不要提交密码、密钥或敏感信息"
              onChange={(event) => setInput(event.target.value)}
              onPressEnter={(event) => {
                if (!event.shiftKey) {
                  event.preventDefault();
                  void send();
                }
              }}
            />
            <Button
              type="primary"
              loading={busy}
              disabled={!input.trim() || !subjectContext?.current_subject_id}
              onClick={() => void send()}
            >
              发送
            </Button>
          </Space.Compact>
        </Card>
      </Space>
    </main>
  );
}
