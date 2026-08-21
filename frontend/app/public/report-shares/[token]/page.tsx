"use client";

import { Alert, Button, Card, Input, Space, Spin, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { publicEnvironment } from "@/lib/env";

type PublicShare = Readonly<{
  password_required: boolean;
  unlocked: boolean;
  summary?: { report_id: string; generated_at: string; brand: Record<string, unknown> };
  report?: {
    report: Record<string, unknown>;
    questions: ReadonlyArray<Record<string, unknown>>;
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
  const payload = (await response.json()) as {
    success: boolean;
    data?: T;
    error?: { message?: string };
  };
  if (!response.ok || !payload.success || payload.data === undefined) {
    throw new Error(payload.error?.message || "分享不可访问");
  }
  return payload.data;
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
      setError(reason instanceof Error ? reason.message : "分享不可访问");
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
      setError(reason instanceof Error ? reason.message : "密码验证失败");
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
      setError(reason instanceof Error ? reason.message : "PDF 暂不可用");
    } finally {
      setBusy(false);
    }
  };

  if (!data && !error) return <Spin fullscreen description="正在读取完整报告快照" />;

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
              description="这是创建分享时冻结的完整报告与品牌快照，不会随主体后续修改而变化。"
            />
            <Card title="报告摘要">
              <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(data.report.report, null, 2)}
              </Typography.Paragraph>
            </Card>
            <Card title={`问题与完整回答（${data.report.questions.length}）`}>
              <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
                {JSON.stringify(data.report.questions, null, 2)}
              </Typography.Paragraph>
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
