"use client";

import { Alert, Card, Col, Empty, Progress, Row, Space, Spin, Tag, Typography } from "antd";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { PlanCatalog } from "@/components/plans/plan-catalog";
import { userMessage } from "@/lib/auth-client";
import { getCurrentSubscription, type Subscription } from "@/lib/plans-client";
import {
  CUSTOMER_QUOTA_PRESENTATION,
  formatQuotaAmount,
  getCurrentQuotaAccounts,
  isUnlimitedQuotaAmount,
  normalizeCustomerQuotaAccounts,
  type CustomerQuotaType,
  type UserQuotaSummary,
} from "@/lib/quota-client";
import { SUBSCRIPTION_STATUS_LABELS } from "@/lib/product-copy";

import styles from "./subscription.module.css";

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

const CORE_SUMMARY_QUOTAS: readonly CustomerQuotaType[] = [
  "geo_detection_runs",
  "article_generations",
  "image_generations",
  "keyword_generated_items",
];

function formatDate(value: string) {
  return new Date(value).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

function planPrice(subscription: Subscription) {
  if (subscription.plan_price_display_mode === "contact") return "按需定制";
  const value = subscription.plan_display_price ?? STANDARD_PRICES[subscription.plan_code];
  if (value === undefined) return "以当前套餐为准";
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
  const rawTotal = account.total_amount ?? account.entitlement_amount;
  const unlimited =
    account.unlimited === true ||
    isUnlimitedQuotaAmount(rawTotal) ||
    isUnlimitedQuotaAmount(account.available);
  if (unlimited) {
    return { total: 0, remaining: 0, frozen: 0, used: 0, unlimited: true };
  }
  const total = Math.max(0, rawTotal);
  const remaining = Math.max(0, account.available);
  const frozen = Math.max(0, account.frozen);
  const used = Math.max(0, account.used_amount ?? total - remaining - frozen);
  return { total, remaining, frozen, used, unlimited: false };
}

export default function CurrentSubscriptionPage() {
  const [current, setCurrent] = useState<Subscription | null | undefined>();
  const [accounts, setAccounts] = useState<UserQuotaSummary[] | null>(null);
  const [error, setError] = useState("");
  const [quotaError, setQuotaError] = useState("");

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
      })
      .catch((value) => setError(userMessage(value)));
  }, []);

  const restrictions = useMemo(() => {
    if (!current) return null;
    const fallback = STANDARD_RESTRICTIONS[current.plan_code];
    return {
      questions: numberLimit(current, "max_questions_per_detection") ?? fallback?.questions,
      models: numberLimit(current, "max_models_per_detection") ?? fallback?.models,
    };
  }, [current]);

  const coreAccounts = useMemo(
    () =>
      CORE_SUMMARY_QUOTAS.flatMap((quotaType) => {
        const account = accounts?.find((item) => item.quota_type === quotaType);
        return account ? [account] : [];
      }),
    [accounts],
  );

  if (error) return <Alert type="error" showIcon title={error} />;
  if (current === undefined) return <Spin description="正在加载套餐与额度" />;

  return (
    <main className={styles.page}>
      <header className={styles.pageHeader}>
        <Typography.Title>套餐与额度</Typography.Title>
        <Typography.Paragraph type="secondary">
          查看当前套餐、对比可选方案，并掌握各项功能的剩余额度。
        </Typography.Paragraph>
      </header>

      <section aria-labelledby="current-plan-title" className={styles.section}>
        <Typography.Title level={2} id="current-plan-title">
          当前套餐
        </Typography.Title>
        {!current ? (
          <Alert
            type="info"
            showIcon
            title="当前尚未开通套餐"
            description="选择适合的套餐后，即可使用对应的检测、内容生成和优化能力。"
          />
        ) : (
          <Card className={styles.summaryCard}>
            <Row gutter={[28, 22]} align="middle">
              <Col xs={24} md={9} xl={7}>
                <Typography.Text type="secondary">当前套餐</Typography.Text>
                <Typography.Title level={2} className={styles.summaryTitle}>
                  {current.plan_name}
                </Typography.Title>
                <Typography.Title level={3} className={styles.summaryPrice}>
                  {planPrice(current)}
                </Typography.Title>
              </Col>
              <Col xs={24} md={15} xl={6}>
                <Space orientation="vertical" size={10}>
                  <Space>
                    <Typography.Text type="secondary">状态</Typography.Text>
                    <Tag color={current.status === "active" ? "green" : "default"}>
                      {SUBSCRIPTION_STATUS_LABELS[current.status]}
                    </Tag>
                  </Space>
                  <Typography.Text>
                    有效期：{formatDate(current.starts_at)} 至 {formatDate(current.ends_at)}
                  </Typography.Text>
                </Space>
              </Col>
              <Col xs={24} xl={11}>
                {accounts === null ? (
                  <Spin description="正在加载核心额度" />
                ) : coreAccounts.length ? (
                  <div className={styles.coreQuotaGrid}>
                    {coreAccounts.map((account) => {
                      const quotaType = account.quota_type as CustomerQuotaType;
                      const presentation = CUSTOMER_QUOTA_PRESENTATION[quotaType];
                      const usage = quotaUsage(account);
                      return (
                        <div className={styles.coreQuota} key={quotaType}>
                          <Typography.Text type="secondary">{presentation.name}</Typography.Text>
                          <Typography.Text strong className={styles.numberLine}>
                            {usage.unlimited
                              ? "不限"
                              : `${formatQuotaAmount(usage.remaining)} / ${formatQuotaAmount(usage.total)} ${presentation.unit}`}
                          </Typography.Text>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <Typography.Text type="secondary">当前暂无可显示的核心额度</Typography.Text>
                )}
                <Link className={styles.inlineLink} href="#current-quotas">
                  查看全部额度 ↓
                </Link>
              </Col>
            </Row>
          </Card>
        )}
      </section>

      <section className={styles.section}>
        <PlanCatalog currentPlanId={current?.plan_id} />
      </section>

      {current ? (
        <section aria-labelledby="current-quotas" className={styles.section}>
          <div className={styles.sectionHeading}>
            <div>
              <Typography.Title level={2} id="current-quotas">
                当前套餐额度
              </Typography.Title>
              <Typography.Paragraph type="secondary">
                额度仅在对应功能成功完成后使用，未完成的操作不会扣减。
              </Typography.Paragraph>
            </div>
          </div>

          {quotaError ? (
            <Alert
              type="warning"
              showIcon
              title="部分额度信息暂时无法显示"
              description="你可以稍后刷新页面查看，已开通的套餐不会受到影响。"
              className={styles.sectionAlert}
            />
          ) : null}

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
                  <Col xs={24} md={12} xl={6} key={quotaType}>
                    <Card className={styles.quotaCard}>
                      <Space orientation="vertical" size={6} style={{ width: "100%" }}>
                        <Typography.Text strong>{presentation.name}</Typography.Text>
                        {usage.unlimited ? (
                          <Typography.Title level={3} className={styles.numberLine}>
                            不限
                          </Typography.Title>
                        ) : (
                          <>
                            <Typography.Title level={3} className={styles.numberLine}>
                              已用 {formatQuotaAmount(usage.used)} /{" "}
                              {formatQuotaAmount(usage.total)} {presentation.unit}
                            </Typography.Title>
                            <Progress percent={percent} showInfo={false} size="small" />
                            <Typography.Text type="secondary" className={styles.numberLine}>
                              剩余 {formatQuotaAmount(usage.remaining)} {presentation.unit}
                              {usage.frozen
                                ? `，处理中 ${formatQuotaAmount(usage.frozen)} ${presentation.unit}`
                                : ""}
                            </Typography.Text>
                          </>
                        )}
                        {isDetection && restrictions?.questions && restrictions.models ? (
                          <Typography.Text type="secondary">
                            单次最多 {restrictions.questions} 个问题 × {restrictions.models} 个模型
                          </Typography.Text>
                        ) : (
                          <Typography.Text type="secondary">
                            {usage.unlimited
                              ? "当前使用不受套餐次数限制"
                              : presentation.shortDescription}
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

          <div className={styles.usageEntry}>
            <Link href="/subscription/usage">查看额度使用记录 →</Link>
          </div>
        </section>
      ) : null}
    </main>
  );
}
