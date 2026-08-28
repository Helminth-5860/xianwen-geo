"use client";

import {
  CheckCircleOutlined,
  ClockCircleOutlined,
  ExclamationCircleOutlined,
  LinkOutlined,
  PauseCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  SendOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Divider,
  Empty,
  Form,
  Input,
  List,
  Modal,
  Radio,
  Row,
  Select,
  Space,
  Spin,
  Statistic,
  Switch,
  Tabs,
  Tag,
  Typography,
  message,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import { getContentLibrary, type Article } from "@/lib/articles-client";
import {
  approvePublicationJob,
  beginPlatformAuthorization,
  createPublicationJob,
  getAutoPublishState,
  getPlatformAuthorization,
  revokePlatformAccount,
  setPlatformParticipation,
  updateAutoPublishPolicy,
  type AuthorizationSession,
  type AutoPublishPolicy,
  type AutoPublishState,
  type PublicationJob,
  type PublicationPlatform,
  type PublicationTarget,
} from "@/lib/publications-client";

import styles from "./auto-publish.module.css";

const { Paragraph, Text, Title } = Typography;

const PLATFORM_PRIMARY = new Set([
  "wechat",
  "toutiao",
  "baijiahao",
  "zhihu",
  "xiaohongshu",
  "weibo",
  "bilibili",
  "douyin",
  "qq",
  "sohu",
]);

const SAFE_TARGET_MESSAGES: Record<string, string> = {
  PUBLICATION_ACCOUNT_AUTH_EXPIRED: "账号授权已失效，请重新授权",
  PUBLICATION_BROWSER_WORKER_UNAVAILABLE: "当前发布服务繁忙，请稍后再试",
  PUBLICATION_PLATFORM_SUBMISSION_FAILED: "平台暂未确认发布结果，系统已停止继续提交",
  PUBLICATION_TEMPORARILY_UNAVAILABLE: "当前平台暂时不可用",
  PUBLICATION_ADAPTATION_FAILED: "平台版本准备失败",
  PUBLICATION_COVER_REQUIRED: "当前平台需要封面图",
};

const TARGET_STATUS: Record<PublicationTarget["status"], { label: string; color?: string }> = {
  waiting: { label: "等待准备" },
  adapting: { label: "正在适配", color: "processing" },
  ready: { label: "准备完成", color: "blue" },
  scheduled: { label: "等待发布", color: "default" },
  publishing: { label: "发布中", color: "processing" },
  published: { label: "已发布", color: "success" },
  failed: { label: "需要处理", color: "error" },
  requires_auth: { label: "需要重新授权", color: "warning" },
  skipped: { label: "已跳过" },
};

function formatDate(value: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function platformAvailability(platform: PublicationPlatform) {
  if (platform.validation_status === "paused") return { text: "暂未开放", color: "default" };
  if (platform.validation_status === "testing") return { text: "正在验证", color: "processing" };
  if (platform.health_status === "unavailable") return { text: "暂不可用", color: "error" };
  if (platform.health_status === "degraded") return { text: "部分异常", color: "warning" };
  return { text: "可自动发布", color: "success" };
}

function PlatformCard({
  platform,
  busy,
  onAuthorize,
  onRevoke,
  onParticipation,
}: {
  platform: PublicationPlatform;
  busy: boolean;
  onAuthorize: (platform: PublicationPlatform) => void;
  onRevoke: (platform: PublicationPlatform) => void;
  onParticipation: (platform: PublicationPlatform, enabled: boolean) => void;
}) {
  const account = platform.account;
  const availability = platformAvailability(platform);
  const authorized = account?.auth_status === "authorized";
  const needsAuth = account?.auth_status === "expired" || account?.auth_status === "needs_verification";
  const canAuthorize = platform.validation_status === "available" && platform.health_status !== "unavailable";

  return (
    <Card className={styles.platformCard} size="small">
      <div className={styles.platformHeader}>
        <div>
          <Space size={8} wrap>
            <Text strong>{platform.name}</Text>
            <Tag color={availability.color}>{availability.text}</Tag>
          </Space>
          <div className={styles.platformMeta}>
            {authorized ? account.display_name || "已授权账号" : needsAuth ? "授权需要更新" : "尚未授权"}
          </div>
        </div>
        {authorized ? (
          <Tag icon={<CheckCircleOutlined />} color="success">
            已授权
          </Tag>
        ) : needsAuth ? (
          <Tag icon={<ExclamationCircleOutlined />} color="warning">
            重新授权
          </Tag>
        ) : (
          <Tag>未授权</Tag>
        )}
      </div>

      <div className={styles.platformActions}>
        {authorized && account ? (
          <>
            <Space size={6}>
              <Switch
                size="small"
                checked={account.enabled_for_auto_publish}
                disabled={busy}
                onChange={(checked) => onParticipation(platform, checked)}
              />
              <Text type="secondary">参与自动发文</Text>
            </Space>
            <Space size={6}>
              <Button size="small" disabled={busy} onClick={() => onAuthorize(platform)}>
                重新授权
              </Button>
              <Button size="small" danger disabled={busy} onClick={() => onRevoke(platform)}>
                解除
              </Button>
            </Space>
          </>
        ) : (
          <Button
            type="primary"
            size="small"
            disabled={!canAuthorize || busy}
            onClick={() => onAuthorize(platform)}
          >
            {needsAuth ? "重新授权" : canAuthorize ? "授权账号" : "暂未开放"}
          </Button>
        )}
      </div>
    </Card>
  );
}

function TargetRow({ target }: { target: PublicationTarget }) {
  const status = TARGET_STATUS[target.status];
  return (
    <div className={styles.targetRow}>
      <div>
        <Space size={8}>
          <Text strong>{target.platform_name}</Text>
          <Tag color={status.color}>{status.label}</Tag>
        </Space>
        <div className={styles.targetMeta}>
          {target.published_at
            ? `发布于 ${formatDate(target.published_at)}`
            : target.scheduled_at
              ? `计划 ${formatDate(target.scheduled_at)}`
              : "等待系统安排"}
        </div>
        {target.safe_error_code && (
          <Text type="secondary">
            {SAFE_TARGET_MESSAGES[target.safe_error_code] || "当前任务需要稍后重新处理"}
          </Text>
        )}
      </div>
      {target.public_url && (
        <Button href={target.public_url} target="_blank" icon={<LinkOutlined />} size="small">
          查看文章
        </Button>
      )}
    </div>
  );
}

function JobCard({ job, onApprove }: { job: PublicationJob; onApprove: (job: PublicationJob) => void }) {
  const awaitingReview = job.distribution_plan.awaiting_review === true;
  return (
    <Card size="small" className={styles.jobCard}>
      <div className={styles.jobHeader}>
        <div>
          <Text strong>{job.article.title}</Text>
          <div className={styles.targetMeta}>创建于 {formatDate(job.created_at)}</div>
        </div>
        <Space wrap>
          {awaitingReview && <Tag color="warning">等待确认</Tag>}
          <Tag>{job.targets.length} 个发布任务</Tag>
          {awaitingReview && (
            <Button type="primary" size="small" onClick={() => onApprove(job)}>
              确认进入自动发布
            </Button>
          )}
        </Space>
      </div>
      <Divider className={styles.compactDivider} />
      <div className={styles.targetList}>
        {job.targets.length ? job.targets.map((target) => <TargetRow key={target.id} target={target} />) : <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="正在规划发布平台" />}
      </div>
    </Card>
  );
}

export default function AutoPublishPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const subjectId = subject?.id ?? "";
  const [state, setState] = useState<AutoPublishState>();
  const [articles, setArticles] = useState<Article[]>([]);
  const [loading, setLoading] = useState(false);
  const [busyKey, setBusyKey] = useState("");
  const [selectedArticleId, setSelectedArticleId] = useState<string>();
  const [authPlatform, setAuthPlatform] = useState<PublicationPlatform>();
  const [authSession, setAuthSession] = useState<AuthorizationSession>();
  const [authSubmitting, setAuthSubmitting] = useState(false);
  const [credentialForm] = Form.useForm<{ app_id: string; app_secret: string }>();
  const [settingsDraft, setSettingsDraft] = useState<AutoPublishPolicy>();
  const [api, contextHolder] = message.useMessage();

  const load = useCallback(async () => {
    if (!subjectId) return;
    setLoading(true);
    try {
      const [nextState, library] = await Promise.all([
        getAutoPublishState(subjectId),
        getContentLibrary(subjectId),
      ]);
      setState(nextState);
      setSettingsDraft(nextState.policy);
      setArticles(
        library.items.filter(
          (article) => article.status === "ready" && article.moderation_status === "passed",
        ),
      );
    } catch (error) {
      api.error(userMessage(error));
    } finally {
      setLoading(false);
    }
  }, [api, subjectId]);

  useEffect(() => {
    if (!subjectLoading && subjectId) void load();
  }, [load, subjectId, subjectLoading]);

  useEffect(() => {
    if (!authSession || !["queued", "waiting"].includes(authSession.status)) return;
    let cancelled = false;
    const timer = window.setInterval(() => {
      void getPlatformAuthorization(authSession.id)
        .then(({ authorization }) => {
          if (cancelled) return;
          setAuthSession(authorization);
          if (authorization.status === "authorized") {
            api.success(`${authorization.platform_name}授权成功`);
            window.clearInterval(timer);
            void load();
          }
        })
        .catch(() => undefined);
    }, 2500);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [api, authSession, load]);

  const primaryPlatforms = useMemo(
    () => state?.platforms.filter((row) => PLATFORM_PRIMARY.has(row.key)) ?? [],
    [state],
  );
  const professionalPlatforms = useMemo(
    () => state?.platforms.filter((row) => !PLATFORM_PRIMARY.has(row.key)) ?? [],
    [state],
  );

  async function savePolicy(next: AutoPublishPolicy) {
    if (!subjectId) return;
    setBusyKey("policy");
    try {
      const { policy } = await updateAutoPublishPolicy(subjectId, {
        enabled: next.enabled,
        operating_mode: next.operating_mode,
        distribution_strategy: next.distribution_strategy,
        custom_platform_keys: next.custom_platform_keys,
        frequency_mode: next.frequency_mode,
        custom_daily_limit: next.custom_daily_limit,
        image_strategy: next.image_strategy,
        image_richness: next.image_richness,
        expected_version: next.version,
      });
      setSettingsDraft(policy);
      setState((current) => (current ? { ...current, policy } : current));
      api.success("自动发文设置已保存");
    } catch (error) {
      api.error(userMessage(error));
      void load();
    } finally {
      setBusyKey("");
    }
  }

  async function toggleMaster(enabled: boolean) {
    if (!settingsDraft) return;
    await savePolicy({ ...settingsDraft, enabled });
  }

  async function startAuthorization(credentials?: { app_id: string; app_secret: string }) {
    if (!authPlatform || !subjectId) return;
    setAuthSubmitting(true);
    try {
      const { authorization } = await beginPlatformAuthorization(
        subjectId,
        authPlatform.key,
        credentials,
      );
      setAuthSession(authorization);
    } catch (error) {
      api.error(userMessage(error));
    } finally {
      setAuthSubmitting(false);
    }
  }

  function openAuthorization(platform: PublicationPlatform) {
    credentialForm.resetFields();
    setAuthSession(undefined);
    setAuthPlatform(platform);
    if (platform.auth_mode === "browser_qr") {
      void startAuthorization();
    }
  }

  async function revoke(platform: PublicationPlatform) {
    if (!subjectId) return;
    setBusyKey(platform.key);
    try {
      await revokePlatformAccount(subjectId, platform.key);
      api.success(`${platform.name}已解除授权`);
      await load();
    } catch (error) {
      api.error(userMessage(error));
    } finally {
      setBusyKey("");
    }
  }

  async function participation(platform: PublicationPlatform, enabled: boolean) {
    if (!subjectId || !platform.account) return;
    setBusyKey(platform.key);
    try {
      await setPlatformParticipation(
        subjectId,
        platform.key,
        enabled,
        platform.account.version,
      );
      await load();
    } catch (error) {
      api.error(userMessage(error));
    } finally {
      setBusyKey("");
    }
  }

  async function arrangeArticle() {
    if (!subjectId || !selectedArticleId) return;
    setBusyKey("article");
    try {
      await createPublicationJob(subjectId, selectedArticleId);
      api.success("文章已进入自动发布流程");
      setSelectedArticleId(undefined);
      await load();
    } catch (error) {
      api.error(userMessage(error));
    } finally {
      setBusyKey("");
    }
  }

  async function approve(job: PublicationJob) {
    setBusyKey(job.id);
    try {
      await approvePublicationJob(job.id);
      api.success("已确认，系统开始准备各平台版本");
      await load();
    } catch (error) {
      api.error(userMessage(error));
    } finally {
      setBusyKey("");
    }
  }

  if (subjectLoading || loading || (subjectId && !state)) {
    return <Spin fullscreen description="正在加载自动发文" />;
  }

  if (!subject) {
    return (
      <main className="geo-dashboard">
        {contextHolder}
        <Card>
          <Empty description="请先创建并选择当前主体">
            <Button type="primary" href="/subjects">
              进入主体与知识
            </Button>
          </Empty>
        </Card>
      </main>
    );
  }

  const policy = settingsDraft ?? state!.policy;

  const overview = (
    <div className={styles.stack}>
      <Card className={styles.heroCard}>
        <div className={styles.heroRow}>
          <div>
            <Space align="center" wrap>
              <Title level={3} className={styles.noMargin}>
                自动发文
              </Title>
              <Tag color={policy.enabled ? "success" : "default"}>
                {policy.enabled ? "运行中" : "已暂停"}
              </Tag>
            </Space>
            <Paragraph type="secondary" className={styles.heroDescription}>
              显问会从可发布文章中自动完成平台适配、智能配图、错峰排期和发布。账号需要重新验证时才需要您处理。
            </Paragraph>
          </div>
          <Space>
            <Text>{policy.enabled ? "自动发文已开启" : "自动发文已暂停"}</Text>
            <Switch
              checked={policy.enabled}
              loading={busyKey === "policy"}
              onChange={(checked) => void toggleMaster(checked)}
            />
          </Space>
        </div>
      </Card>

      <Row gutter={[16, 16]}>
        <Col xs={12} lg={6}>
          <Card><Statistic title="已授权平台" value={state!.summary.authorized} suffix={`/ ${state!.summary.platform_total}`} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="今日计划" value={state!.summary.today_planned} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="今日已发布" value={state!.summary.today_published} /></Card>
        </Col>
        <Col xs={12} lg={6}>
          <Card><Statistic title="需要处理" value={state!.summary.needs_attention} /></Card>
        </Col>
      </Row>

      <Card title="安排一篇已生成文章" extra={<Button icon={<ReloadOutlined />} onClick={() => void load()}>刷新</Button>}>
        <Paragraph type="secondary">
          全自动托管开启后，达到可发布状态的文章会自动进入流程。您也可以在这里立即安排一篇已生成文章。
        </Paragraph>
        <Space.Compact className={styles.articlePicker}>
          <Select
            value={selectedArticleId}
            onChange={setSelectedArticleId}
            placeholder={articles.length ? "选择已准备好的文章" : "暂无可发布文章"}
            options={articles.map((article) => ({ value: article.id, label: article.title || "未命名文章" }))}
            disabled={!articles.length}
            showSearch
            optionFilterProp="label"
          />
          <Button
            type="primary"
            icon={<SendOutlined />}
            disabled={!selectedArticleId}
            loading={busyKey === "article"}
            onClick={() => void arrangeArticle()}
          >
            进入自动发布
          </Button>
        </Space.Compact>
      </Card>

      <Card title="今日发布计划">
        {state!.today_targets.length ? (
          <div className={styles.targetList}>
            {state!.today_targets.map((target) => <TargetRow key={target.id} target={target} />)}
          </div>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="今天还没有待执行的发布计划" />
        )}
      </Card>

      {state!.summary.needs_attention > 0 && (
        <Alert
          type="warning"
          showIcon
          message="有发布任务需要处理"
          description="通常是账号授权已失效或平台暂时未确认发布结果。其他正常平台会继续执行。"
        />
      )}
    </div>
  );

  const authorization = (
    <div className={styles.stack}>
      <Alert
        type="info"
        showIcon
        icon={<SafetyCertificateOutlined />}
        message="账号密码不会交给显问"
        description="支持正式接口的平台优先使用官方授权；需要网页登录的平台由您本人扫码或完成平台要求的验证。显问只加密保存授权会话。"
      />
      <section>
        <Title level={4}>主流内容平台</Title>
        <div className={styles.platformGrid}>
          {primaryPlatforms.map((platform) => (
            <PlatformCard
              key={platform.key}
              platform={platform}
              busy={busyKey === platform.key}
              onAuthorize={openAuthorization}
              onRevoke={(row) => void revoke(row)}
              onParticipation={(row, enabled) => void participation(row, enabled)}
            />
          ))}
        </div>
      </section>
      <section>
        <Title level={4}>专业内容平台</Title>
        <div className={styles.platformGrid}>
          {professionalPlatforms.map((platform) => (
            <PlatformCard
              key={platform.key}
              platform={platform}
              busy={busyKey === platform.key}
              onAuthorize={openAuthorization}
              onRevoke={(row) => void revoke(row)}
              onParticipation={(row, enabled) => void participation(row, enabled)}
            />
          ))}
        </div>
      </section>
    </div>
  );

  const settings = (
    <Card>
      <div className={styles.settingsGrid}>
        <div>
          <Text strong>发文模式</Text>
          <Radio.Group
            className={styles.radioStack}
            value={policy.operating_mode}
            onChange={(event) => setSettingsDraft({ ...policy, operating_mode: event.target.value })}
          >
            <Radio value="managed">全自动托管 — 显问自动接管达到发布条件的文章</Radio>
            <Radio value="review">审核后发布 — 准备完成后由您确认再发布</Radio>
            <Radio value="selected">仅发布指定内容 — 只处理您主动安排的文章</Radio>
          </Radio.Group>
        </div>
        <div>
          <Text strong>发布策略</Text>
          <Radio.Group
            className={styles.radioStack}
            value={policy.distribution_strategy}
            onChange={(event) => setSettingsDraft({ ...policy, distribution_strategy: event.target.value })}
          >
            <Radio value="smart">智能分发 — 根据文章内容选择更合适的平台</Radio>
            <Radio value="all_authorized">所有已授权平台 — 每篇都覆盖全部可用平台</Radio>
            <Radio value="custom">自定义平台</Radio>
          </Radio.Group>
          {policy.distribution_strategy === "custom" && (
            <Select
              mode="multiple"
              className={styles.fullWidth}
              placeholder="选择参与的平台"
              value={policy.custom_platform_keys}
              onChange={(keys) => setSettingsDraft({ ...policy, custom_platform_keys: keys })}
              options={state!.platforms.map((platform) => ({ label: platform.name, value: platform.key }))}
            />
          )}
        </div>
        <div>
          <Text strong>发布频率</Text>
          <Radio.Group
            className={styles.radioStack}
            value={policy.frequency_mode}
            onChange={(event) => setSettingsDraft({ ...policy, frequency_mode: event.target.value })}
          >
            <Radio value="smart">智能安排</Radio>
            <Radio value="daily_1">每天 1 篇</Radio>
            <Radio value="daily_2">每天 2 篇</Radio>
            <Radio value="daily_3">每天 3 篇</Radio>
          </Radio.Group>
        </div>
        <div>
          <Text strong>图片策略</Text>
          <Radio.Group
            className={styles.radioStack}
            value={policy.image_strategy}
            onChange={(event) => setSettingsDraft({ ...policy, image_strategy: event.target.value })}
          >
            <Radio value="customer_only">仅使用企业素材</Radio>
            <Radio value="prefer_customer">企业素材优先，不足时自动补图</Radio>
            <Radio value="auto">全自动配图</Radio>
          </Radio.Group>
        </div>
        <div>
          <Text strong>配图丰富度</Text>
          <Radio.Group
            value={policy.image_richness}
            onChange={(event) => setSettingsDraft({ ...policy, image_richness: event.target.value })}
          >
            <Radio.Button value="simple">简洁</Radio.Button>
            <Radio.Button value="standard">标准</Radio.Button>
            <Radio.Button value="rich">丰富</Radio.Button>
          </Radio.Group>
          <Paragraph type="secondary" className={styles.settingHelp}>
            标准模式默认准备 1 张封面和 2 张正文插图。优先复用企业真实素材，缺少时才生成概念性配图。
          </Paragraph>
        </div>
      </div>
      <Divider />
      <Button
        type="primary"
        loading={busyKey === "policy"}
        onClick={() => void savePolicy(policy)}
      >
        保存设置
      </Button>
    </Card>
  );

  const records = (
    <div className={styles.stack}>
      {state!.recent_jobs.length ? (
        state!.recent_jobs.map((job) => (
          <JobCard key={job.id} job={job} onApprove={(row) => void approve(row)} />
        ))
      ) : (
        <Card><Empty description="还没有发布记录" /></Card>
      )}
    </div>
  );

  return (
    <main className="geo-dashboard">
      {contextHolder}
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">CONTENT DISTRIBUTION</Text>
          <Title level={2}>自动发文</Title>
          <Paragraph type="secondary">
            当前主体：{subject.official_name || subject.subject_type.name}。授权平台后，显问可自动完成图文准备、平台适配、错峰发布和结果记录。
          </Paragraph>
        </div>
        <Button href="/geo/articles/new">进入文章生成</Button>
      </section>

      <Tabs
        items={[
          { key: "overview", label: "运行概览", children: overview },
          { key: "authorization", label: `平台授权 ${state!.summary.authorized}/${state!.summary.platform_total}`, children: authorization },
          { key: "settings", label: "发布设置", children: settings },
          { key: "records", label: "发布记录", children: records },
        ]}
      />

      <Modal
        open={Boolean(authPlatform)}
        title={authPlatform ? `授权${authPlatform.name}` : "平台授权"}
        footer={null}
        width={720}
        destroyOnClose
        onCancel={() => {
          setAuthPlatform(undefined);
          setAuthSession(undefined);
        }}
      >
        {authPlatform?.auth_mode === "official_credentials" ? (
          <>
            <Alert
              showIcon
              type="info"
              message="使用平台官方开发凭据授权"
              description="这里填写的是公众号后台提供的 AppID 和 AppSecret，不是账号登录密码。凭据只会加密保存。"
            />
            <Form
              form={credentialForm}
              layout="vertical"
              className={styles.authForm}
              onFinish={(values) => void startAuthorization(values)}
            >
              <Form.Item name="app_id" label="AppID" rules={[{ required: true, message: "请输入 AppID" }]}>
                <Input autoComplete="off" />
              </Form.Item>
              <Form.Item name="app_secret" label="AppSecret" rules={[{ required: true, message: "请输入 AppSecret" }]}>
                <Input.Password autoComplete="new-password" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={authSubmitting || authSession?.status === "queued"}>
                验证并授权
              </Button>
            </Form>
          </>
        ) : (
          <>
            <Alert
              showIcon
              type="info"
              message="请使用平台账号完成扫码"
              description="显问不会要求您提供平台密码。若平台要求额外短信、人机或安全验证，系统会停止自动操作并提示您重新授权。"
            />
            <div className={styles.authSnapshot}>
              {authSession?.login_snapshot_data_url ? (
                // eslint-disable-next-line @next/next/no-img-element -- short-lived authenticated platform login screenshot
                <img src={authSession.login_snapshot_data_url} alt={`${authPlatform?.name ?? "平台"}登录页面`} />
              ) : authSession?.status === "failed" ? (
                <Empty description="当前无法打开平台授权页面，请稍后重试" />
              ) : authSession?.status === "needs_interaction" ? (
                <Empty description="平台要求额外安全验证，请稍后重新授权" />
              ) : authSession?.status === "authorized" ? (
                <Empty image={<CheckCircleOutlined className={styles.successIcon} />} description="授权成功" />
              ) : (
                <Spin description="正在打开平台登录页面" />
              )}
            </div>
            <Paragraph type="secondary">
              授权窗口约 6 分钟有效。二维码刷新时，本页面会自动更新。
            </Paragraph>
          </>
        )}

        {authSession && (
          <Descriptions size="small" column={1} bordered>
            <Descriptions.Item label="授权状态">
              {authSession.status === "authorized"
                ? "已授权"
                : authSession.status === "waiting"
                  ? "等待扫码"
                  : authSession.status === "queued"
                    ? "正在准备"
                    : authSession.status === "needs_interaction"
                      ? "需要额外验证"
                      : authSession.status === "expired"
                        ? "本次授权已过期"
                        : authSession.status === "failed"
                          ? "授权暂未完成"
                          : "已取消"}
            </Descriptions.Item>
          </Descriptions>
        )}
      </Modal>
    </main>
  );
}
