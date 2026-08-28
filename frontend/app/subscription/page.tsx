"use client";

import { Alert, Card, Descriptions, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { SubscriptionChangeHistory } from "@/components/subscription-change-history";
import { getCurrentSubscription, type Subscription } from "@/lib/plans-client";
import { SUBSCRIPTION_STATUS_LABELS } from "@/lib/product-copy";

export default function CurrentSubscriptionPage() {
  const [current, setCurrent] = useState<Subscription | null | undefined>();
  const [error, setError] = useState("");
  useEffect(() => {
    void getCurrentSubscription()
      .then((data) => setCurrent(data.current))
      .catch((value) => setError(userMessage(value)));
  }, []);
  if (error) return <Alert type="error" showIcon message={error} />;
  if (current === undefined) return <Spin description="正在加载当前套餐" />;
  return (
    <main className="auth-page">
      <Typography.Title>我的套餐</Typography.Title>
      {!current ? (
        <Alert
          type="info"
          showIcon
          message="当前尚未开通套餐"
          description="选择适合的套餐后，即可使用对应的关键词、检测和内容生成能力。"
        />
      ) : (
        <Card>
          <Descriptions column={1}>
            <Descriptions.Item label="套餐">{current.plan_name}</Descriptions.Item>
            <Descriptions.Item label="类型">
              {current.is_trial ? "试用套餐" : "正式套餐"}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag>{SUBSCRIPTION_STATUS_LABELS[current.status]}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="生效时间">
              {new Date(current.starts_at).toLocaleString("zh-CN")}
            </Descriptions.Item>
            <Descriptions.Item label="有效期至">
              {new Date(current.ends_at).toLocaleString("zh-CN")}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}
      <SubscriptionChangeHistory />
    </main>
  );
}
