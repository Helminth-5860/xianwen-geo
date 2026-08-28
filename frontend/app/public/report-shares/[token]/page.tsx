"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  Input,
  List,
  Row,
  Space,
  Spin,
  Statistic,
  Tag,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { publicEnvironment } from "@/lib/env";
import type { GeoReport, ReportQuestionPage } from "@/lib/geo-report-client";
import {
  aiModelDisplayName,
  safeLocalProductMessage,
  userFacingApiError,
} from "@/lib/product-copy";

type SharedResult = ReportQuestionPage["results"][number]["results"][number] & {
  full_answer: string | null;
};

type SharedQuestion = Omit<ReportQuestionPage["results"][number], "results"> & {
  results: ReadonlyArray<SharedResult>;
};

type PublicShare = Readonly<{
  password_required: boolean;
  unlocked: boolean;
  summary?: { report_id: string; generated_at: string; brand: Record<string, unknown> };
  report?: {
    report: GeoReport;
    questions: ReadonlyArray<SharedQuestion>;
  };
  brand?: Record<string, unknown>;
  pdf_available?: boolean;
}>;

async function publicRequest<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${publicEnvironment.apiBaseUrl}${path}`, {
    credentials: "include",
    cache: "no-store",
    ...init,
    headers: { Accept: "application/json", "Content-Type": "application/json", ...init?.headers },
  });
  let payload: { success: boolean; data?: T; error?: { code?: string; message?: string } };
  try {
    payload = (await response.json()) as typeof payload;
  } catch {
    throw new Error("当前报告暂时无法加载，请稍后再试。");
  }
  if (!response.ok || !payload.success || payload.data === undefined) {
    throw new Error(userFacingApiError({ code: payload.error?.code, status: response.status }));
  }
  return payload.data;
}

const answerStatusLabels: Readonly<Record<string, string>> = Object.freeze({
  queued: "等待检测",
  running: "正在检测",
  succeeded: "检测完成",
  failed: "未能完成",
  cancelled: "已取消",
});

function reportScore(value: string | null | undefined) {
  return value === null || value === undefined || value === "" ? "—" : value;
}

export default function PublicReportSharePage() {
  const { token } = useParams<{ token: string }>();
  const encodedToken = encodeURIComponent(token);
  const [data, setData] = useState<PublicShare>();
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setData(await publicRequest<PublicShare>(`/public/report-shares/${encodedToken}`));
      setError("");
    } catch (reason) {
      setError(
        reason instanceof Error
          ? safeLocalProductMessage(reason.message, "该报告分享暂时无法访问。")
          : "该报告分享暂时无法访问。",
      );
    }
  }, [encodedToken]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const unlock = async () => {
    setBusy(true);
    try {
      await publicRequest(`/public/report-shares/${encodedToken}/unlock`, {
        method: "POST",
        body: JSON.stringify({ password }),
      });
      await load();
    } catch (reason) {
      setError(
        reason instanceof Error
          ? safeLocalProductMessage(reason.message, "密码验证未通过，请重新输入。")
          : "密码验证未通过，请重新输入。",
      );
    } finally {
      setBusy(false);
    }
  };

  const downloadPdf = async () => {
    setBusy(true);
    try {
      const result = await publicRequest<{ download_url: string }>(
        `/public/report-shares/${encodedToken}/pdf`,
      );
      window.location.assign(result.download_url);
    } catch (reason) {
      setError(
        reason instanceof Error
          ? safeLocalProductMessage(reason.message, "报告文件暂时无法下载，请稍后再试。")
          : "报告文件暂时无法下载，请稍后再试。",
      );
    } finally {
      setBusy(false);
    }
  };

  if (!data && !error) return <Spin fullscreen description="正在加载完整报告" />;

  const sharedReport = data?.report?.report;
  const sharedQuestions = data?.report?.questions ?? [];

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Typography.Title level={2}>GEO 完整报告分享</Typography.Title>
        {error && <Alert type="error" showIcon title={error} />}
        {data?.password_required && !data.unlocked && (
          <Card title="此分享需要密码">
            <Space>
              <Input.Password
                aria-label="分享访问密码"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
              <Button type="primary" loading={busy} onClick={() => void unlock()}>
                解锁
              </Button>
            </Space>
          </Card>
        )}
        {data?.unlocked && data.report && (
          <>
            <Alert
              type="info"
              title={`品牌：${String(data.brand?.brand_name ?? "显问 GEO")}`}
              description="这是创建分享时的报告内容，之后修改企业资料不会改变这份报告。"
            />
            <Card title="报告概览">
              <Row gutter={[16, 16]}>
                <Col xs={24} md={8}>
                  <Statistic
                    title="GEO 综合评分"
                    value={reportScore(sharedReport?.summary.geo.score)}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <Statistic
                    title="品牌口碑评分"
                    value={reportScore(sharedReport?.summary.brand_reputation.score)}
                  />
                </Col>
                <Col xs={24} md={8}>
                  <Statistic
                    title="曝光指数"
                    value={reportScore(sharedReport?.summary.exposure.exposure_index)}
                  />
                </Col>
              </Row>
              {sharedReport?.generated_at ? (
                <Typography.Text type="secondary">
                  报告生成时间：{new Date(sharedReport.generated_at).toLocaleString("zh-CN")}
                </Typography.Text>
              ) : null}
            </Card>
            <Card title={`检测问题与回答（${sharedQuestions.length}）`}>
              <List
                dataSource={[...sharedQuestions]}
                pagination={{ pageSize: 20, hideOnSinglePage: true, showSizeChanger: false }}
                locale={{ emptyText: "这份报告暂时没有可展示的检测问题。" }}
                renderItem={(question, index) => (
                  <List.Item>
                    <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                      <Typography.Title level={5} style={{ margin: 0 }}>
                        {index + 1}. {question.text}
                      </Typography.Title>
                      <List
                        size="small"
                        dataSource={[...question.results]}
                        renderItem={(result) => (
                          <List.Item key={result.call_id}>
                            <Space orientation="vertical" size="small" style={{ width: "100%" }}>
                              <Space wrap>
                                <Typography.Text strong>
                                  {aiModelDisplayName(result.model_key)}
                                </Typography.Text>
                                <Tag>{answerStatusLabels[result.status] ?? "状态待确认"}</Tag>
                              </Space>
                              <Typography.Paragraph style={{ whiteSpace: "pre-wrap", margin: 0 }}>
                                {result.full_answer || result.snippet || "本次未获得可展示的回答。"}
                              </Typography.Paragraph>
                              {result.citations.length > 0 ? (
                                <Space wrap>
                                  <Typography.Text type="secondary">引用来源：</Typography.Text>
                                  {result.citations.map((citation) => (
                                    <Typography.Link
                                      key={`${result.call_id}-${citation.url}`}
                                      href={citation.url}
                                      target="_blank"
                                      rel="noreferrer"
                                    >
                                      {citation.title || citation.source_name || "查看来源"}
                                    </Typography.Link>
                                  ))}
                                </Space>
                              ) : null}
                            </Space>
                          </List.Item>
                        )}
                      />
                    </Space>
                  </List.Item>
                )}
              />
            </Card>
            <Button type="primary" loading={busy} onClick={() => void downloadPdf()}>
              下载完整 PDF
            </Button>
          </>
        )}
      </Space>
    </main>
  );
}
