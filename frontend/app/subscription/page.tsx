"use client";

import { Alert, Card, Descriptions, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { SubscriptionChangeHistory } from "@/components/subscription-change-history";
import { getCurrentSubscription, type Subscription } from "@/lib/plans-client";

export default function CurrentSubscriptionPage() {
  const [current, setCurrent] = useState<Subscription | null | undefined>();
  const [error, setError] = useState("");
  useEffect(() => {
    void getCurrentSubscription()
      .then((data) => setCurrent(data.current))
      .catch((value) => setError(userMessage(value)));
  }, []);
  if (error) return <Alert type="error" showIcon message={error} />;
  if (current === undefined) return <Spin description="正在加载当前订阅" />;
  return (
    <main className="auth-page">
      <Typography.Title>我的订阅</Typography.Title>
      {!current ? (
        <Alert type="info" showIcon message="当前尚未开通套餐" />
      ) : (
        <Card>
          <Descriptions column={1}>
            <Descriptions.Item label="套餐">{current.plan_name}</Descriptions.Item>
            <Descriptions.Item label="版本">第 {current.plan_version_no} 版</Descriptions.Item>
            <Descriptions.Item label="类型">
              {current.is_trial ? "试用套餐" : "正式套餐"}
            </Descriptions.Item>
            <Descriptions.Item label="状态">
              <Tag>{current.status}</Tag>
            </Descriptions.Item>
            <Descriptions.Item label="开始时间">{current.starts_at}</Descriptions.Item>
            <Descriptions.Item label="结束时间">{current.ends_at}</Descriptions.Item>
          </Descriptions>
        </Card>
      )}
      <SubscriptionChangeHistory />
    </main>
  );
}
