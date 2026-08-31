"use client";

import {
  Alert,
  Card,
  Col,
  Empty,
  Progress,
  Row,
  Select,
  Space,
  Spin,
  Table,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { SubscriptionChangeHistory } from "@/components/subscription-change-history";
import { userMessage } from "@/lib/auth-client";
import { getCurrentSubscription, type Subscription } from "@/lib/plans-client";
import {
  CUSTOMER_QUOTA_PRESENTATION,
  CUSTOMER_QUOTA_TYPES,
  customerQuotaPresentation,
  customerQuotaType,
  getCurrentQuotaAccounts,
  getUserQuotaLedger,
  normalizeCustomerQuotaAccounts,
  type CustomerQuotaType,
  type UserQuotaLedgerEntry,
  type UserQuotaSummary,
} from "@/lib/quota-client";
import { safeLocalProductMessage, SUBSCRIPTION_STATUS_LABELS } from "@/lib/product-copy";

const STANDARD_PRICES: Readonly<Record<string, string>> = {
  "free-trial": "0.00",
  "starter-1980": "1980.00",
  "professional-6980": "6980.00",
  "advanced-12980": "12980.00",
};

const STANDARD_RESTRICTIONS: Readonly<Record<string, { questions: number; models: number }>> = {
  "free-trial": { questions: 5, models: 3 },
  "starter-1980": { questions: 10, models: 8 },
  "professional-6980": { questions: 20, models: 8 },
  "advanced-12980": { questions: 30, models: 8 },
};

const LEDGER_ACTIONS: Readonly<
  Record<string, { label: string; status: string; direction: "increase" | "decrease" | "hold" }>
> = {
  initialize: { label: "套餐额度已开通", status: "已完成", direction: "increase" },
  freeze: { label: "本次使用额度已预留", status: "处理中", direction: "hold" },
  consume: { label: "额度已使用", status: "已完成", direction: "decrease" },
  release: { label: "未使用额度已返还", status: "已退回", direction: "increase" },
  grant: { label: "额度已增加", status: "已完成", direction: "increase" },
  compensate: { label: "额度已补发", status: "已完成", direction: "increase" },
  refund: { label: "额度已返还", status: "已完成", direction: "increase" },
  manual_deduct: { label: "额度已扣减", status: "已完成", direction: "decrease" },
  "manual-deduct": { label: "额度已扣减", status: "已完成", direction: "decrease" },
  plan_change_transfer_in: { label: "套餐调整额度转入", status: "已完成", direction: "increase" },
  plan_change_transfer_out: { label: "套餐调整额度转出", status: "已完成", direction: "decrease" },
  plan_change_forfeit: { label: "原套餐额度已结束", status: "已完成", direction: "decrease" },
  expiry_forfeit: { label: "套餐到期额度已结束", status: "已完成", direction: "decrease" },
};

function formatDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function planPrice(subscription: Subscription) {
  if (subscription.plan_price_display_mode === "contact") return "联系开通";
  const value = subscription.plan_display_price ?? STANDARD_PRICES[subscription.plan_code];
  if (value === undefined) return "以开通方案为准";
  return Number(value) === 0 ? "免费" : `¥${Number(value).toLocaleString("zh-CN")}`;
}

function numberLimit(subscription: Subscription, key: string) {
  const direct =
    key === "max_models_per_detection"
      ? subscription.entitlement_summary.max_models_per_detection
      : subscription.entitlement_summary.max_questions_per_detection;
  if (typeof direct === "number") return direct;
  const value = subscription.entitlement_summary.limits?.[key];
  return typeof value === "number" ? value : undefined;
}

function quotaUsage(account: UserQuotaSummary) {
  const total = Math.max(0, account.total_amount ?? account.entitlement_amount);
  const remaining = Math.max(0, account.available);
  const frozen = Math.max(0, account.frozen);
  const used = Math.max(0, account.used_amount ?? total - remaining - frozen);
  return { total, remaining, frozen, used };
}

function ledgerAmount(entry: UserQuotaLedgerEntry) {
  if (typeof entry.amount === "number") return Math.abs(entry.amount);
  if (entry.action === "consume" || entry.action === "release") {
    return Math.abs(entry.frozen_delta || entry.available_delta);
  }
  return Math.abs(entry.available_delta || entry.frozen_delta);
}

function ledgerBefore(entry: UserQuotaLedgerEntry) {
  return entry.available_before ?? entry.available_after - entry.available_delta;
}

export default function CurrentSubscriptionPage() {
  const [current, setCurrent] = useState<Subscription | null | undefined>();
  const [accounts, setAccounts] = useState<UserQuotaSummary[] | null>(null);
  const [ledger, setLedger] = useState<UserQuotaLedgerEntry[]>([]);
  const [ledgerPage, setLedgerPage] = useState(1);
  const [ledgerTotal, setLedgerTotal] = useState(0);
  const [quotaFilter, setQuotaFilter] = useState("");
  const [error, setError] = useState("");
  const [quotaError, setQuotaError] = useState("");
  const [ledgerLoading, setLedgerLoading] = useState(false);

  const loadLedger = useCallback(async (page = 1, quotaType = "") => {
    setLedgerLoading(true);
    try {
      const data = await getUserQuotaLedger(page, quotaType);
      setLedger(data.results.filter((item) => customerQuotaType(item.quota_type) !== null));
      setLedgerTotal(data.pagination.count);
      setLedgerPage(data.pagination.page);
    } catch (reason) {
      setQuotaError(userMessage(reason));
    } finally {
      setLedgerLoading(false);
    }
  }, []);

  useEffect(() => {
    void getCurrentSubscription()
      .then((data) => {
        setCurrent(data.current);
        if (!data.current) {
          setAccounts([]);
          return;
        }
        void getCurrentQuotaAccounts()
          .then((quotaData) => setAccounts(normalizeCustomerQuotaAccounts(quotaData.accounts)))
          .catch((reason) => {
            setAccounts([]);
            setQuotaError(userMessage(reason));
          });
        void loadLedger();
      })
      .catch((value) => setError(userMessage(value)));
  }, [loadLedger]);

  const restrictions = useMemo(() => {
    if (!current) return null;
    const fallback = STANDARD_RESTRICTIONS[current.plan_code];
    return {
      questions: numberLimit(current, "max_questions_per_detection") ?? fallback?.questions,
      models: numberLimit(current, "max_models_per_detection") ?? fallback?.models,
    };
  }, [current]);

  if (error) return <Alert type="error" showIcon message={error} />;
  if (current === undefined) return <Spin description="正在加载套餐与额度" />;
  return (
    <main className="auth-page">
      <Typography.Title>套餐与额度</Typography.Title>
      {!current ? (
        <Alert
          type="info"
          showIcon
          message="当前尚未开通套餐"
          description="选择适合的套餐后，即可使用对应的检测、内容生成和优化能力。"
        />
      ) : (
        <>
          <Card style={{ marginBottom: 20 }}>
            <Row gutter={[24, 18]} align="middle">
              <Col xs={24} md={8}>
                <Typography.Text type="secondary">当前套餐</Typography.Text>
                <Typography.Title level={2} style={{ margin: "4px 0 0" }}>
                  {current.plan_name}
                </Typography.Title>
              </Col>
              <Col xs={12} md={5}>
                <Typography.Text type="secondary">套餐价格</Typography.Text>
                <Typography.Title level={3} style={{ margin: "4px 0 0" }}>
                  {planPrice(current)}
                </Typography.Title>
              </Col>
              <Col xs={12} md={4}>
                <Typography.Text type="secondary">套餐状态</Typography.Text>
                <div style={{ marginTop: 8 }}>
                  <Tag color={current.status === "active" ? "green" : "default"}>
                    {SUBSCRIPTION_STATUS_LABELS[current.status]}
                  </Tag>
                </div>
              </Col>
              <Col xs={24} md={7}>
                <Typography.Text type="secondary">有效期</Typography.Text>
                <Typography.Paragraph style={{ margin: "5px 0 0" }}>
                  {formatDate(current.starts_at)} 至 {formatDate(current.ends_at)}
                </Typography.Paragraph>
              </Col>
            </Row>
          </Card>

          {quotaError ? (
            <Alert
              type="warning"
              showIcon
              message="部分额度信息暂时无法显示"
              description="你可以稍后刷新页面查看，已开通的套餐不会受到影响。"
              style={{ marginBottom: 20 }}
            />
          ) : null}

          <Typography.Title level={3}>可用额度</Typography.Title>
          {accounts === null ? (
            <Spin description="正在加载可用额度" />
          ) : accounts.length ? (
            <Row gutter={[16, 16]}>
              {accounts.map((account) => {
                const quotaType = account.quota_type as CustomerQuotaType;
                const presentation = CUSTOMER_QUOTA_PRESENTATION[quotaType];
                const usage = quotaUsage(account);
                const percent = usage.total
                  ? Math.min(100, Math.round((usage.used / usage.total) * 100))
                  : 0;
                const isDetection = quotaType === "geo_detection_runs";
                return (
                  <Col xs={24} sm={12} xl={8} key={quotaType}>
                    <Card>
                      <Space direction="vertical" size={5} style={{ width: "100%" }}>
                        <Typography.Text strong>{presentation.name}</Typography.Text>
                        <Typography.Title level={3} style={{ margin: 0 }}>
                          {usage.used} / {usage.total} {presentation.unit}
                        </Typography.Title>
                        <Progress percent={percent} showInfo={false} size="small" />
                        <Typography.Text type="secondary">
                          剩余 {usage.remaining} {presentation.unit}
                          {usage.frozen ? `，处理中 ${usage.frozen} ${presentation.unit}` : ""}
                        </Typography.Text>
                        {isDetection && restrictions?.questions && restrictions.models ? (
                          <Typography.Text type="secondary">
                            单次最多 {restrictions.questions} 个问题 × {restrictions.models} 个模型
                          </Typography.Text>
                        ) : (
                          <Typography.Text type="secondary">
                            {presentation.shortDescription}
                          </Typography.Text>
                        )}
                      </Space>
                    </Card>
                  </Col>
                );
              })}
            </Row>
          ) : (
            <Empty description="当前套餐暂时没有可显示的额度" />
          )}

          <Card title="额度使用记录" style={{ marginTop: 22 }}>
            <Select
              aria-label="按功能筛选额度记录"
              value={quotaFilter}
              style={{ width: 220, marginBottom: 16 }}
              options={[
                { value: "", label: "全部功能" },
                ...CUSTOMER_QUOTA_TYPES.map((quotaType) => ({
                  value: quotaType,
                  label: CUSTOMER_QUOTA_PRESENTATION[quotaType].name,
                })),
              ]}
              onChange={(value) => {
                setQuotaFilter(value);
                void loadLedger(1, value);
              }}
            />
            <Table<UserQuotaLedgerEntry>
              rowKey="id"
              loading={ledgerLoading}
              dataSource={ledger}
              scroll={{ x: 860 }}
              locale={{
                emptyText: (
                  <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无额度使用记录" />
                ),
              }}
              pagination={{
                current: ledgerPage,
                pageSize: 20,
                total: ledgerTotal,
                showSizeChanger: false,
                onChange: (page) => void loadLedger(page, quotaFilter),
              }}
              columns={[
                { title: "时间", render: (_, item) => formatDate(item.created_at), width: 170 },
                {
                  title: "功能",
                  render: (_, item) =>
                    customerQuotaPresentation(item.quota_type)?.name ?? "套餐额度",
                  width: 140,
                },
                {
                  title: "操作说明",
                  render: (_, item) =>
                    safeLocalProductMessage(
                      item.description ?? item.safe_reason ?? "",
                      item.action_label ?? LEDGER_ACTIONS[item.action]?.label ?? "额度发生变化",
                    ),
                },
                {
                  title: "额度变化",
                  render: (_, item) => {
                    const action = LEDGER_ACTIONS[item.action];
                    const unit = customerQuotaPresentation(item.quota_type)?.unit ?? "";
                    const amount = ledgerAmount(item);
                    if (action?.direction === "hold") return `预留 ${amount} ${unit}`;
                    return `${action?.direction === "decrease" ? "减少" : "增加"} ${amount} ${unit}`;
                  },
                  width: 130,
                },
                {
                  title: "变化前后",
                  render: (_, item) => `${ledgerBefore(item)} → ${item.available_after}`,
                  width: 120,
                },
                {
                  title: "状态",
                  render: (_, item) => (
                    <Tag
                      color={
                        item.action === "release"
                          ? "blue"
                          : item.action === "freeze"
                            ? "gold"
                            : "green"
                      }
                    >
                      {item.status_label ?? LEDGER_ACTIONS[item.action]?.status ?? "已完成"}
                    </Tag>
                  ),
                  width: 100,
                },
                {
                  title: "关联内容",
                  render: (_, item) =>
                    safeLocalProductMessage(item.related_object ?? "", "本次额度变更"),
                  width: 160,
                },
              ]}
            />
          </Card>
        </>
      )}
      <SubscriptionChangeHistory />
    </main>
  );
}
