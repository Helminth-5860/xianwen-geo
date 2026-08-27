"use client";

import { Alert, Button, Card, Input, List, Select, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  checkPublication,
  getPublicationChecks,
  getPublishingChannels,
  getSubjectArticles,
  type Article,
  type PublicationCheck,
  type PublishingChannel,
} from "@/lib/articles-client";
import { userMessage } from "@/lib/auth-client";

type Props = Readonly<{ subjectId: string }>;

const resultPresentation: Readonly<
  Record<PublicationCheck["result"], { color: string; label: string }>
> = {
  success: { color: "success", label: "发布成功" },
  failed: { color: "error", label: "未检测到对应文章" },
  unknown: { color: "warning", label: "暂时无法判断" },
};

function inferredChannelId(url: string, channels: PublishingChannel[]) {
  let hostname = "";
  try {
    hostname = new URL(url).hostname.toLowerCase();
  } catch {
    return "";
  }
  const matched = channels.find((channel) => {
    if (channel.key === "website") return false;
    try {
      const officialHostname = new URL(channel.official_url).hostname.toLowerCase();
      return hostname === officialHostname || hostname.endsWith(`.${officialHostname}`);
    } catch {
      return false;
    }
  });
  return matched?.id || channels.find((channel) => channel.key === "website")?.id || "";
}

export function PublicationCheckWorkspace({ subjectId }: Props) {
  const [articles, setArticles] = useState<Article[]>([]);
  const [channels, setChannels] = useState<PublishingChannel[]>([]);
  const [checks, setChecks] = useState<PublicationCheck[]>([]);
  const [articleId, setArticleId] = useState("");
  const [url, setUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<PublicationCheck>();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [articleRows, channelRows, historyRows] = await Promise.all([
        getSubjectArticles(subjectId, 1, 100),
        getPublishingChannels(),
        getPublicationChecks(subjectId, 1, 20),
      ]);
      const readyArticles = articleRows.items.filter(
        (article) => article.status === "ready" && Boolean(article.content.trim()),
      );
      setArticles(readyArticles);
      setChannels(channelRows.items);
      setChecks(historyRows.items);
      setArticleId((current) =>
        readyArticles.some((article) => article.id === current)
          ? current
          : (readyArticles[0]?.id ?? ""),
      );
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const articleById = useMemo(
    () => Object.fromEntries(articles.map((article) => [article.id, article])),
    [articles],
  );
  const channelById = useMemo(
    () => Object.fromEntries(channels.map((channel) => [channel.id, channel])),
    [channels],
  );

  const submit = async () => {
    if (!articleId || !url.trim()) return;
    const channelId = inferredChannelId(url.trim(), channels);
    if (!channelId) {
      setError("发布渠道配置暂不可用，请稍后重试。");
      return;
    }
    try {
      const parsed = new URL(url.trim());
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error();
    } catch {
      setError("请输入完整的公开文章链接，例如 https://example.com/article。");
      return;
    }
    setChecking(true);
    setError("");
    setResult(undefined);
    try {
      const created = await checkPublication(subjectId, articleId, channelId, url.trim());
      setResult(created);
      setChecks((current) =>
        [created, ...current.filter((item) => item.id !== created.id)].slice(0, 20),
      );
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setChecking(false);
    }
  };

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div>
          <Typography.Title level={2}>发布检测</Typography.Title>
          <Typography.Text type="secondary">
            粘贴公开文章链接，核验页面是否可访问并与系统内生成的文章内容一致。
          </Typography.Text>
        </div>
        <Alert
          type="info"
          showIcon
          title="这里只检测发布结果，不会代替您登录第三方平台或自动发布文章。"
        />
        {error && <Alert type="error" showIcon title={error} />}
        {loading ? (
          <Spin description="正在加载可检测文章" />
        ) : (
          <>
            <Card title="检测公开文章链接">
              <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
                {!articles.length ? (
                  <Alert
                    type="warning"
                    showIcon
                    title="当前主体还没有可用于比对的已生成文章"
                    description="请先在文章生成页面完成正文生成，再回来检测公开链接。"
                  />
                ) : (
                  <Select
                    aria-label="选择待检测文章"
                    value={articleId || undefined}
                    placeholder="选择要核验的文章"
                    options={articles.map((article) => ({
                      value: article.id,
                      label: article.title || "未命名文章",
                    }))}
                    onChange={setArticleId}
                  />
                )}
                <Input
                  aria-label="公开文章链接"
                  value={url}
                  placeholder="粘贴公开文章链接，例如 https://..."
                  onChange={(event) => setUrl(event.target.value)}
                  onPressEnter={() => void submit()}
                />
                <Button
                  type="primary"
                  loading={checking}
                  disabled={!articleId || !url.trim() || checking}
                  onClick={() => void submit()}
                >
                  检测是否发布成功
                </Button>
                {result && (
                  <Alert
                    type={result.result === "success" ? "success" : "warning"}
                    showIcon
                    title={resultPresentation[result.result].label}
                    description={result.match_summary}
                  />
                )}
              </Space>
            </Card>
            <Card title="最近检测记录">
              <List
                dataSource={checks}
                locale={{ emptyText: "暂无检测记录" }}
                renderItem={(item) => (
                  <List.Item
                    actions={[
                      <Typography.Link
                        key="url"
                        href={item.url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        打开链接
                      </Typography.Link>,
                    ]}
                  >
                    <List.Item.Meta
                      title={
                        articleById[item.article_id || ""]?.title ||
                        item.detected_title ||
                        "公开文章"
                      }
                      description={`${channelById[item.channel_id]?.name || "公开网页"} · ${item.match_summary}`}
                    />
                    <Tag color={resultPresentation[item.result].color}>
                      {resultPresentation[item.result].label}
                    </Tag>
                  </List.Item>
                )}
              />
            </Card>
          </>
        )}
      </Space>
    </main>
  );
}
