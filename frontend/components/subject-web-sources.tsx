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

const webSourceStatusLabels: Readonly<Record<string, string>> = {
  queued: "等待导入",
  fetching: "正在导入",
  retry_wait: "等待再次处理",
  succeeded: "可以确认",
  failed: "导入未完成",
};

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
      setMessage("正在导入公开网页内容，完成后即可查看并确认。");
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
        setMessage("网页暂时无法导入，请稍后重新尝试。");
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
        仅支持无需登录即可访问的公开网页。系统不会使用你的登录信息，也不会打开网页中的其他内容。
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
      {message && <Alert type="info" showIcon message={message} />}
      <Space.Compact style={{ width: "100%", marginBottom: 16 }}>
        <Input
          aria-label="公开网页地址"
          value={url}
          disabled={disabled || busy}
          placeholder="粘贴公开网页链接"
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
        locale={{ emptyText: "还没有网页资料，粘贴公开网页链接后即可导入。" }}
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
              <Tag>{webSourceStatusLabels[source.status] ?? "状态待确认"}</Tag>
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
