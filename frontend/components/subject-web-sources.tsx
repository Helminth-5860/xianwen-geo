"use client";

import { Alert, Button, Card, Input, List, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  confirmWebSource,
  getWebSource,
  importWebSource,
  listWebSources,
  type WebSourceImport,
} from "@/lib/web-sources-client";

export function SubjectWebSources({
  subjectId,
  disabled = false,
}: {
  subjectId: string;
  disabled?: boolean;
}) {
  const [url, setUrl] = useState("");
  const [sources, setSources] = useState<WebSourceImport[]>([]);
  const [active, setActive] = useState<WebSourceImport>();
  const [confirmedText, setConfirmedText] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  const refresh = async () => {
    const result = await listWebSources(subjectId);
    setSources(result.results);
  };

  useEffect(() => {
    let current = true;
    void listWebSources(subjectId)
      .then((result) => current && setSources(result.results))
      .catch((reason) => current && setError(userMessage(reason)));
    return () => {
      current = false;
    };
  }, [subjectId]);

  const submit = async () => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      let source = await importWebSource(subjectId, url);
      setMessage("网页导入任务已受理，系统正在安全抓取公开内容");
      for (
        let attempt = 0;
        attempt < 30 && ["queued", "fetching", "retry_wait"].includes(source.status);
        attempt += 1
      ) {
        await new Promise((resolve) => window.setTimeout(resolve, 800));
        source = await getWebSource(source.id);
      }
      setActive(source);
      setConfirmedText(source.latest_version?.canonical_text ?? "");
      if (source.status === "succeeded") {
        setMessage("抓取完成，请检查并确认网页文本");
      } else if (source.status === "retry_wait") {
        setMessage("网页抓取暂时不可用，系统会安全重试");
      } else if (source.status === "failed") {
        setError("网页内容未能安全导入");
      }
      setUrl("");
      await refresh();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  const confirm = async () => {
    if (!active?.latest_version) return;
    setBusy(true);
    try {
      await confirmWebSource(active, active.latest_version.id, confirmedText);
      const refreshed = await getWebSource(active.id);
      setActive(refreshed);
      setMessage("网页文本已确认");
      setError("");
      await refresh();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card title="公开网页资料" style={{ marginBottom: 20 }}>
      <Typography.Paragraph type="secondary">
        仅支持公开 HTTP/HTTPS 网页。系统不会登录网站、携带 Cookie、执行脚本或加载子资源。
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
      {message && <Alert type="info" showIcon message={message} />}
      <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
        <Input
          aria-label="公开网页地址"
          value={url}
          disabled={disabled || busy}
          placeholder="https://example.com/public-page"
          onChange={(event) => setUrl(event.target.value)}
        />
        <Button
          type="primary"
          loading={busy}
          disabled={disabled || !url.trim()}
          onClick={() => void submit()}
        >
          导入网页
        </Button>
      </Space.Compact>
      <List
        dataSource={sources}
        locale={{ emptyText: "暂无网页资料" }}
        renderItem={(source) => (
          <List.Item
            actions={[
              <Button
                key="review"
                type="link"
                disabled={source.status !== "succeeded"}
                onClick={() => {
                  setActive(source);
                  setConfirmedText(source.latest_version?.canonical_text ?? "");
                }}
              >
                查看并确认
              </Button>,
            ]}
          >
            <Space>
              <Typography.Text>{source.display_url}</Typography.Text>
              {source.has_query && <Tag>含查询参数，已隐藏</Tag>}
              <Tag>{source.status}</Tag>
            </Space>
          </List.Item>
        )}
      />
      {active?.latest_version && (
        <Card title="网页文本确认" size="small">
          <Alert
            type="warning"
            showIcon
            message="网页内容不可信；确认前不会提供给任何后续业务能力"
          />
          <Input.TextArea
            aria-label="确认网页文本"
            rows={10}
            value={confirmedText}
            disabled={disabled || busy}
            onChange={(event) => setConfirmedText(event.target.value)}
          />
          <Button type="primary" loading={busy} disabled={disabled} onClick={() => void confirm()}>
            确认网页文本
          </Button>
        </Card>
      )}
    </Card>
  );
}
