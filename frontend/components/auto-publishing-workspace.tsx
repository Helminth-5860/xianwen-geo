"use client";

import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  LinkOutlined,
  PauseCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
  SettingOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  InputNumber,
  Modal,
  Radio,
  Skeleton,
  Space,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { getSubjectArticles, type Article } from "@/lib/articles-client";
import { userMessage } from "@/lib/auth-client";
import {
  approvePublication,
  createPublication,
  disconnectPlatform,
  getAuthorizationSession,
  getPublishingState,
  setPlatformAutoEnabled,
  startPlatformAuthorization,
  updatePublishingPreference,
  type AuthorizationSession,
  type PublishingPlatform,
  type PublishingState,
} from "@/lib/publishing-client";

import styles from "./auto-publishing-workspace.module.css";

const TERMINAL_AUTH_STATES = new Set<AuthorizationSession["status"]>([
  "succeeded",
  "failed",
  "expired",
]);

const platformStatus = (platform: PublishingPlatform) => {
  if (!platform.authorization_enabled) {
    return { color: "default", text: "适配验证中" } as const;
  }
  const status = platform.account?.status;
  if (status === "connected") return { color: "success", text: "已授权" } as const;
  if (status === "authorizing") return { color: "processing", text: "授权中" } as const;
  if (status === "expired" || status === "action_required") {
    return { color: "warning", text: "需要重新授权" } as const;
  }
  if (status === "suspended") return { color: "default", text: "已暂停" } as const;
  return { color: "default", text: "未授权" } as const;
};

const targetStatusText: Record<string, string> = {
  waiting: "等待发布",
  ready: "已准备",
  running: "正在发布",
  submitted: "平台审核中",
  succeeded: "已发布",
  failed: "发布失败",
  auth_required: "需要重新授权",
  paused: "已暂停",
};

const publicationStatusText: Record<string, string> = {
  preparing: "正在准备",
  queued: "等待发布",
  running: "正在处理",
  paused: "已暂停",
  partial: "部分完成",
  succeeded: "发布完成",
  failed: "发布未完成",
  cancelled: "已取消",
};

export function AutoPublishingWorkspace() {
  const { currentSubject, loading: subjectLoading } = useSubjectWorkspace();
  const [messageApi, messageHolder] = message.useMessage();
  const [state, setState] = useState<PublishingState | null>(null);
  const [readyArticles, setReadyArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [queueingArticleId, setQueueingArticleId] = useState<string | null>(null);
  const [approvingPublicationId, setApprovingPublicationId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [authSession, setAuthSession] = useState<AuthorizationSession | null>(null);
  const [authPlatformName, setAuthPlatformName] = useState("");
  const [authModalOpen, setAuthModalOpen] = useState(false);
  const authWindowRef = useRef<Window | null>(null);

  const loadState = useCallback(async (subjectId: string) => {
    setLoading(true);
    setError("");
    try {
      const [publishing, articlePage] = await Promise.all([
        getPublishingState(subjectId),
        getSubjectArticles(subjectId, 1, 50),
      ]);
      setState(publishing);
      const alreadyScheduled = new Set(
        publishing.recent_publications.map((item) => item.article_id),
      );
      setReadyArticles(
        articlePage.items.filter(
          (article) =>
            article.status === "ready" &&
            article.moderation_status === "passed" &&
            !alreadyScheduled.has(article.id),
        ),
      );
    } catch (reason: unknown) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!currentSubject?.id) return;
    const timer = window.setTimeout(() => void loadState(currentSubject.id), 0);
    return () => window.clearTimeout(timer);
  }, [currentSubject?.id, loadState]);

  useEffect(() => {
    if (!authModalOpen || !authSession || TERMINAL_AUTH_STATES.has(authSession.status)) return;
    let alive = true;
    const timer = window.setInterval(() => {
      void getAuthorizationSession(authSession.id)
        .then(({ authorization }) => {
          if (!alive) return;
          setAuthSession(authorization);
          if (authorization.status === "succeeded") {
            messageApi.success(`${authPlatformName}授权成功`);
            if (currentSubject?.id) void loadState(currentSubject.id);
          }
        })
        .catch(() => undefined);
    }, 1800);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [authModalOpen, authPlatformName, authSession, currentSubject?.id, loadState, messageApi]);

  const savePreference = async (changes: Record<string, unknown>) => {
    if (!currentSubject?.id || !state) return;
    setSaving(true);
    setError("");
    try {
      const response = await updatePublishingPreference(currentSubject.id, {
        ...changes,
        expected_version: state.preference.version,
      });
      setState((current) => (current ? { ...current, preference: response.preference } : current));
      await loadState(currentSubject.id);
    } catch (reason: unknown) {
      setError(userMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  const beginAuthorization = async (platform: PublishingPlatform) => {
    if (!currentSubject?.id || !platform.authorization_enabled) return;
    try {
      const { authorization } = await startPlatformAuthorization(currentSubject.id, platform.key);
      setAuthPlatformName(platform.name);
      setAuthSession(authorization);
      setAuthModalOpen(true);
      if (authorization.action_url) {
        authWindowRef.current = window.open(
          authorization.action_url,
          `xianwen-auth-${authorization.id}`,
          "popup=yes,width=1120,height=760,resizable=yes,scrollbars=yes",
        );
      }
      await loadState(currentSubject.id);
    } catch (reason: unknown) {
      messageApi.warning(userMessage(reason));
    }
  };

  const togglePlatform = async (platform: PublishingPlatform, enabled: boolean) => {
    if (!currentSubject?.id || !platform.account) return;
    try {
      await setPlatformAutoEnabled(currentSubject.id, platform.key, enabled);
      messageApi.success(
        enabled ? `${platform.name}已恢复自动发文` : `${platform.name}已暂停自动发文`,
      );
      await loadState(currentSubject.id);
    } catch (reason: unknown) {
      messageApi.error(userMessage(reason));
    }
  };

  const removePlatform = async (platform: PublishingPlatform) => {
    if (!currentSubject?.id || !platform.account) return;
    Modal.confirm({
      title: `解除${platform.name}授权？`,
      content: "解除后不会删除已经发布的文章；尚未提交的平台任务会暂停，后续重新授权后可继续安排。",
      okText: "解除授权",
      cancelText: "取消",
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await disconnectPlatform(currentSubject.id, platform.key);
          await loadState(currentSubject.id);
        } catch (reason: unknown) {
          messageApi.error(userMessage(reason));
        }
      },
    });
  };

  const queueArticle = async (article: Article) => {
    if (!currentSubject?.id) return;
    setQueueingArticleId(article.id);
    try {
      await createPublication(currentSubject.id, { article_id: article.id });
      messageApi.success(
        state?.preference.mode === "review"
          ? "文章正在准备，完成后会等待你确认发布"
          : "文章已进入自动发布流程",
      );
      await loadState(currentSubject.id);
    } catch (reason: unknown) {
      messageApi.warning(userMessage(reason));
    } finally {
      setQueueingArticleId(null);
    }
  };

  const confirmPublication = async (publicationId: string) => {
    if (!currentSubject?.id) return;
    setApprovingPublicationId(publicationId);
    try {
      await approvePublication(publicationId);
      messageApi.success("已确认，显问将按计划错峰发布");
      await loadState(currentSubject.id);
    } catch (reason: unknown) {
      messageApi.warning(userMessage(reason));
    } finally {
      setApprovingPublicationId(null);
    }
  };

  const platformGroups = useMemo(() => {
    const platforms = state?.platforms ?? [];
    return {
      mainstream: platforms.filter((item) => item.category === "mainstream"),
      professional: platforms.filter((item) => item.category === "professional"),
    };
  }, [state?.platforms]);

  if (subjectLoading) {
    return (
      <main className="page-shell">
        <Skeleton active paragraph={{ rows: 8 }} />
      </main>
    );
  }

  if (!currentSubject) {
    return (
      <main className="page-shell">
        <Empty description="请先选择一个主体，再开启自动发文" />
      </main>
    );
  }

  if (!state && loading) {
    return (
      <main className="page-shell">
        <Skeleton active paragraph={{ rows: 8 }} />
      </main>
    );
  }

  const preference = state?.preference;
  const summary = state?.summary;

  const overview = (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <div className={styles.summaryGrid}>
        <div className={styles.summaryCard}>
          <Typography.Text type="secondary">已授权平台</Typography.Text>
          <div className={styles.summaryValue}>
            {summary?.connected_count ?? 0} / {summary?.platform_count ?? 17}
          </div>
        </div>
        <div className={styles.summaryCard}>
          <Typography.Text type="secondary">今日计划</Typography.Text>
          <div className={styles.summaryValue}>{summary?.today_plan_count ?? 0}</div>
        </div>
        <div className={styles.summaryCard}>
          <Typography.Text type="secondary">今日已发布</Typography.Text>
          <div className={styles.summaryValue}>{summary?.today_published_count ?? 0}</div>
        </div>
        <div className={styles.summaryCard}>
          <Typography.Text type="secondary">需要处理</Typography.Text>
          <div className={styles.summaryValue}>{summary?.needs_action_count ?? 0}</div>
        </div>
      </div>

      {!preference?.is_enabled && (
        <Alert
          type="warning"
          showIcon
          title="自动发文当前已暂停"
          description="尚未提交的平台任务已经暂停。重新开启后，显问会继续未完成的任务；已经提交平台审核或已经发布的内容不会重复处理。"
        />
      )}

      <Card className={styles.sectionCard} title="待发布内容">
        {!readyArticles.length ? (
          <div className={styles.emptyPlan}>当前没有等待安排的可发布文章。</div>
        ) : (
          <Space orientation="vertical" size="small" style={{ width: "100%" }}>
            {readyArticles.slice(0, 10).map((article) => (
              <Space
                key={article.id}
                wrap
                style={{ justifyContent: "space-between", width: "100%" }}
              >
                <div>
                  <Typography.Text strong>{article.title || "未命名文章"}</Typography.Text>
                  <div>
                    <Typography.Text type="secondary">
                      已完成内容审核，可由显问自动配图、适配平台并排期发布
                    </Typography.Text>
                  </div>
                </div>
                <Button
                  type="primary"
                  size="small"
                  loading={queueingArticleId === article.id}
                  disabled={!summary?.connected_count}
                  onClick={() => void queueArticle(article)}
                >
                  安排发布
                </Button>
              </Space>
            ))}
          </Space>
        )}
      </Card>

      <Card className={styles.sectionCard} title="最近发布任务">
        {!state?.recent_publications.length ? (
          <div className={styles.emptyPlan}>
            还没有发布任务。文章进入可发布状态后，显问会按照你的设置安排分发。
          </div>
        ) : (
          <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
            {state.recent_publications.slice(0, 8).map((publication) => (
              <Card key={publication.id} size="small">
                <Space orientation="vertical" size={8} style={{ width: "100%" }}>
                  <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
                    <Typography.Text strong>{publication.title}</Typography.Text>
                    <Space>
                      <Tag color={publication.awaiting_review ? "gold" : undefined}>
                        {publication.awaiting_review
                          ? "等待确认"
                          : (publicationStatusText[publication.status] ?? "等待处理")}
                      </Tag>
                      {publication.awaiting_review && (
                        <Button
                          size="small"
                          type="primary"
                          loading={approvingPublicationId === publication.id}
                          disabled={!preference?.is_enabled}
                          onClick={() => void confirmPublication(publication.id)}
                        >
                          确认发布
                        </Button>
                      )}
                    </Space>
                  </Space>
                  <div className={styles.targetList}>
                    {publication.targets.map((target) => (
                      <Tag
                        key={target.id}
                        color={
                          target.status === "succeeded"
                            ? "success"
                            : target.status === "submitted"
                              ? "processing"
                              : target.status === "failed" || target.status === "auth_required"
                                ? "warning"
                                : "default"
                        }
                      >
                        {target.platform_name} · {targetStatusText[target.status] ?? "处理中"}
                      </Tag>
                    ))}
                  </div>
                </Space>
              </Card>
            ))}
          </Space>
        )}
      </Card>
    </Space>
  );

  const renderPlatformGroup = (title: string, platforms: PublishingPlatform[]) => (
    <Card className={styles.sectionCard} title={title}>
      <div className={styles.platformGrid}>
        {platforms.map((platform) => {
          const badge = platformStatus(platform);
          const connected = platform.account?.status === "connected";
          return (
            <div className={styles.platformCard} key={platform.key}>
              <div className={styles.platformHeader}>
                <div>
                  <h3 className={styles.platformName}>{platform.name}</h3>
                  <div className={styles.platformMeta}>
                    {platform.auth_method === "official_api"
                      ? "优先使用平台正式授权"
                      : "通过安全登录窗口完成授权"}
                  </div>
                </div>
                <Tag color={badge.color}>{badge.text}</Tag>
              </div>

              <div className={styles.platformMeta}>
                {connected && platform.account?.display_name
                  ? `账号：${platform.account.display_name}`
                  : platform.authorization_enabled
                    ? "客户本人完成扫码或平台要求的验证；必要输入只在临时授权窗口转发，不保存到显问数据库。"
                    : "适配器完成真实账号验证后开放，不会把未验证能力展示成可用。"}
              </div>

              <div className={styles.platformActions}>
                {connected ? (
                  <Space size="small">
                    <Switch
                      size="small"
                      checked={platform.account?.enabled_for_auto ?? false}
                      onChange={(checked) => void togglePlatform(platform, checked)}
                    />
                    <Typography.Text type="secondary">参与自动发文</Typography.Text>
                  </Space>
                ) : (
                  <Typography.Text type="secondary">
                    {platform.authorization_enabled ? "等待授权" : "等待开放"}
                  </Typography.Text>
                )}

                {connected ? (
                  <Button size="small" type="text" onClick={() => void removePlatform(platform)}>
                    解除授权
                  </Button>
                ) : (
                  <Button
                    size="small"
                    type="primary"
                    disabled={!platform.authorization_enabled}
                    onClick={() => void beginAuthorization(platform)}
                  >
                    {platform.account?.needs_action ? "重新授权" : "授权账号"}
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </Card>
  );

  const platforms = (
    <Space orientation="vertical" size="large" style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="授权信息不会被明文保存"
        description="客户本人在安全授权窗口完成扫码或平台要求的验证。若平台要求手机号、验证码或密码，输入内容仅临时转发到当前隔离浏览器，不写入数据库或日志；登录成功后只加密保存平台会话凭证。"
      />
      {renderPlatformGroup("主流内容平台", platformGroups.mainstream)}
      {renderPlatformGroup("专业内容平台", platformGroups.professional)}
    </Space>
  );

  const settings = preference ? (
    <Card className={styles.sectionCard}>
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <div className={styles.settingBlock}>
          <Space style={{ justifyContent: "space-between", width: "100%" }}>
            <div>
              <div className={styles.settingTitle}>自动发文</div>
              <div className={styles.settingHint}>
                关闭后会暂停尚未提交的平台任务；已经提交审核或已经发布的内容不会被撤回或重复发布。
              </div>
            </div>
            <Switch
              checked={preference.is_enabled}
              loading={saving}
              onChange={(checked) => void savePreference({ is_enabled: checked })}
            />
          </Space>
        </div>

        <div className={styles.settingGrid}>
          <div className={styles.settingBlock}>
            <div className={styles.settingTitle}>发文模式</div>
            <Radio.Group
              value={preference.mode}
              onChange={(event) => void savePreference({ mode: event.target.value })}
            >
              <Space orientation="vertical">
                <Radio value="managed">全自动托管</Radio>
                <Radio value="review">审核后发布</Radio>
                <Radio value="selected">仅发布指定内容</Radio>
              </Space>
            </Radio.Group>
            <div className={styles.settingHint}>
              全自动托管会自动接管可发布文章；审核后发布会先完成配图和平台适配，再等待你点一次“确认发布”；仅发布指定内容只处理你主动安排的文章。
            </div>
          </div>

          <div className={styles.settingBlock}>
            <div className={styles.settingTitle}>发布策略</div>
            <Radio.Group
              value={preference.distribution_strategy}
              onChange={(event) =>
                void savePreference({ distribution_strategy: event.target.value })
              }
            >
              <Space orientation="vertical">
                <Radio value="smart">智能分发</Radio>
                <Radio value="all">所有已授权平台</Radio>
                <Radio value="custom">自定义平台</Radio>
              </Space>
            </Radio.Group>
            <div className={styles.settingHint}>
              智能分发会根据文章类型、主题和内容形态选择更适合的平台，默认不会机械铺满所有账号。
            </div>
          </div>

          <div className={styles.settingBlock}>
            <div className={styles.settingTitle}>图片策略</div>
            <Radio.Group
              value={preference.image_strategy}
              onChange={(event) => void savePreference({ image_strategy: event.target.value })}
            >
              <Space orientation="vertical">
                <Radio value="customer_only">仅使用企业素材</Radio>
                <Radio value="customer_first">企业素材优先，不足自动补图</Radio>
                <Radio value="ai_auto">全自动配图</Radio>
              </Space>
            </Radio.Group>
            <div className={styles.settingHint}>
              默认优先真实企业图片；AI 只补充概念图、封面背景、流程图等视觉素材。
            </div>
          </div>

          <div className={styles.settingBlock}>
            <div className={styles.settingTitle}>配图丰富度</div>
            <Radio.Group
              value={preference.image_density}
              onChange={(event) => void savePreference({ image_density: event.target.value })}
              optionType="button"
              buttonStyle="solid"
              options={[
                { label: "简洁", value: "compact" },
                { label: "标准", value: "standard" },
                { label: "丰富", value: "rich" },
              ]}
            />
            <div className={styles.settingHint}>
              标准模式通常包含 1 张封面、2–4 张正文插图，必要时增加信息图。
            </div>
          </div>

          <div className={styles.settingBlock}>
            <div className={styles.settingTitle}>发布频率</div>
            <Radio.Group
              value={preference.frequency_mode}
              onChange={(event) => void savePreference({ frequency_mode: event.target.value })}
            >
              <Space orientation="vertical">
                <Radio value="smart">智能安排</Radio>
                <Radio value="fixed">固定频率</Radio>
              </Space>
            </Radio.Group>
            {preference.frequency_mode === "fixed" && (
              <Space style={{ marginTop: 12 }}>
                <Typography.Text>每天</Typography.Text>
                <InputNumber
                  min={1}
                  max={10}
                  value={preference.posts_per_day}
                  onChange={(value) => value && void savePreference({ posts_per_day: value })}
                />
                <Typography.Text>篇</Typography.Text>
              </Space>
            )}
            <div className={styles.settingHint}>不同平台会自动错峰发布，避免同一时间集中提交。</div>
          </div>

          <div className={styles.settingBlock}>
            <div className={styles.settingTitle}>默认执行原则</div>
            <Space orientation="vertical" size={8}>
              <Typography.Text>
                <SafetyCertificateOutlined /> 真实企业素材优先
              </Typography.Text>
              <Typography.Text>
                <ClockCircleOutlined /> 平台自动错峰
              </Typography.Text>
              <Typography.Text>
                <PauseCircleOutlined /> 单个平台异常不会拖停其他平台
              </Typography.Text>
              <Typography.Text>
                <SendOutlined /> 只有拿到公开链接才标记“已发布”
              </Typography.Text>
            </Space>
          </div>
        </div>
      </Space>
    </Card>
  ) : null;

  const records = (
    <Card className={styles.sectionCard}>
      {!state?.recent_publications.length ? (
        <Empty description="暂无发布记录" />
      ) : (
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          {state.recent_publications.map((publication) => (
            <Card key={publication.id} size="small">
              <Space orientation="vertical" size={10} style={{ width: "100%" }}>
                <Space wrap style={{ justifyContent: "space-between", width: "100%" }}>
                  <Typography.Text strong>{publication.title}</Typography.Text>
                  <Space>
                    <Tag color={publication.awaiting_review ? "gold" : undefined}>
                      {publication.awaiting_review
                        ? "等待确认"
                        : (publicationStatusText[publication.status] ?? "等待处理")}
                    </Tag>
                    {publication.awaiting_review && (
                      <Button
                        size="small"
                        type="primary"
                        loading={approvingPublicationId === publication.id}
                        disabled={!preference?.is_enabled}
                        onClick={() => void confirmPublication(publication.id)}
                      >
                        确认发布
                      </Button>
                    )}
                  </Space>
                </Space>
                {publication.targets.map((target) => (
                  <Space
                    key={target.id}
                    wrap
                    style={{ justifyContent: "space-between", width: "100%" }}
                  >
                    <Space>
                      {target.status === "succeeded" ? (
                        <CheckCircleOutlined />
                      ) : (
                        <ClockCircleOutlined />
                      )}
                      <Typography.Text>{target.platform_name}</Typography.Text>
                      <Tag color={target.status === "submitted" ? "processing" : undefined}>
                        {targetStatusText[target.status] ?? "处理中"}
                      </Tag>
                    </Space>
                    {target.public_url ? (
                      <Button
                        size="small"
                        type="link"
                        href={target.public_url}
                        target="_blank"
                        icon={<LinkOutlined />}
                      >
                        查看文章
                      </Button>
                    ) : target.status === "submitted" ? (
                      <Typography.Text type="secondary">已提交平台，等待审核</Typography.Text>
                    ) : target.error_message ? (
                      <Typography.Text type="warning">{target.error_message}</Typography.Text>
                    ) : null}
                  </Space>
                ))}
              </Space>
            </Card>
          ))}
        </Space>
      )}
    </Card>
  );

  return (
    <main className="page-shell">
      {messageHolder}
      <div className={styles.workspace}>
        <section className={styles.hero}>
          <div>
            <Typography.Text type="secondary">当前主体</Typography.Text>
            <h1 className={styles.heroTitle}>
              {state?.subject.official_name || currentSubject.official_name || "当前主体"}
            </h1>
            <p className={styles.heroDescription}>
              显问会从可发布文章中自动完成平台判断、智能配图、内容适配、错峰排期和发布。客户只需要完成平台授权，并决定是否开启自动发文。
            </p>
          </div>
          <Space>
            <Button
              icon={<ReloadOutlined />}
              loading={loading}
              onClick={() => void loadState(currentSubject.id)}
            >
              刷新状态
            </Button>
            <Space>
              <Typography.Text strong>
                {preference?.is_enabled ? "自动发文已开启" : "自动发文已关闭"}
              </Typography.Text>
              <Switch
                checked={preference?.is_enabled ?? false}
                loading={saving}
                onChange={(checked) => void savePreference({ is_enabled: checked })}
              />
            </Space>
          </Space>
        </section>

        {error && <Alert type="warning" showIcon title={error} />}

        <Tabs
          defaultActiveKey="overview"
          items={[
            { key: "overview", label: "运行概览", children: overview },
            {
              key: "platforms",
              label: `平台授权 ${summary?.connected_count ?? 0}/${summary?.platform_count ?? 17}`,
              children: platforms,
            },
            {
              key: "settings",
              label: (
                <span>
                  <SettingOutlined /> 发布设置
                </span>
              ),
              children: settings,
            },
            { key: "records", label: "发布记录", children: records },
          ]}
        />
      </div>

      <Modal
        open={authModalOpen}
        title={`授权${authPlatformName}`}
        footer={[
          <Button key="close" onClick={() => setAuthModalOpen(false)}>
            关闭
          </Button>,
          authSession?.action_url ? (
            <Button
              key="open"
              type="primary"
              onClick={() => {
                authWindowRef.current = window.open(
                  authSession.action_url,
                  `xianwen-auth-${authSession.id}`,
                  "popup=yes,width=1120,height=760,resizable=yes,scrollbars=yes",
                );
              }}
            >
              重新打开授权窗口
            </Button>
          ) : null,
        ]}
        onCancel={() => setAuthModalOpen(false)}
      >
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Alert
            type="info"
            showIcon
            title="请优先使用扫码完成登录"
            description="如平台要求手机号、验证码或密码，请先在授权画面中点击对应输入框，再使用授权窗口下方的临时输入栏。输入内容只转发到当前隔离浏览器，不保存到显问数据库或日志。"
          />
          <Typography.Text>
            当前状态：
            {authSession?.status === "succeeded"
              ? "授权成功"
              : authSession?.status === "failed"
                ? "授权未完成"
                : authSession?.status === "expired"
                  ? "授权已过期"
                  : "等待完成登录"}
          </Typography.Text>
          {authSession?.error_message && (
            <Alert type="warning" showIcon title={authSession.error_message} />
          )}
          {!authSession?.action_url &&
            authSession &&
            !TERMINAL_AUTH_STATES.has(authSession.status) && (
              <Alert type="warning" showIcon title="授权窗口正在准备，请稍后重试" />
            )}
        </Space>
      </Modal>
    </main>
  );
}
