"use client";

import { Alert, Button, Card, Empty, List, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { userMessage } from "@/lib/auth-client";
import { getPublicPlans, type PublicPlan } from "@/lib/plans-client";

export function PlanCatalog() {
  const [plans, setPlans] = useState<PublicPlan[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void getPublicPlans()
      .then(setPlans)
      .catch((reason) => setError(userMessage(reason)));
  }, []);
  if (error) return <Alert type="error" message="套餐加载失败" description={error} />;
  if (!plans) return <Spin description="正在加载套餐" />;
  if (!plans.length) return <Empty description="当前暂无可用套餐" />;
  return (
    <section aria-labelledby="plans-title">
      <Typography.Title level={2} id="plans-title">
        可用套餐
      </Typography.Title>
      <List
        grid={{ gutter: 16, xs: 1, md: 2, lg: 3 }}
        dataSource={plans}
        renderItem={(plan) => (
          <List.Item>
            <Card title={plan.name}>
              <Typography.Paragraph>{plan.description}</Typography.Paragraph>
              <Typography.Title level={3}>
                {plan.price_display_mode === "fixed" ? `¥${plan.display_price}` : "联系开通"}
              </Typography.Title>
              <Space wrap>
                <Tag>{plan.valid_days} 天</Tag>
                <Tag color={plan.supports_formal_composite ? "green" : "orange"}>
                  {plan.supports_formal_composite ? "支持正式综合分" : "不支持正式综合分"}
                </Tag>
              </Space>
              <Typography.Paragraph>
                模型：{plan.models.map((item) => item.name).join("、")}
              </Typography.Paragraph>
              <Button href="/login">申请套餐 / 联系开通</Button>
              <Typography.Paragraph type="secondary">
                不提供在线购买，不会创建申请或订单。
              </Typography.Paragraph>
            </Card>
          </List.Item>
        )}
      />
    </section>
  );
}
