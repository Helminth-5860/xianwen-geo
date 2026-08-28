"use client";

import { Alert, Card, List, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getUserSubscriptionChanges, type SubscriptionChange } from "@/lib/plans-client";
import {
  SUBSCRIPTION_CHANGE_STATUS_LABELS,
  SUBSCRIPTION_CHANGE_TYPE_LABELS,
} from "@/lib/product-copy";

export function SubscriptionChangeHistory() {
  const [items, setItems] = useState<SubscriptionChange[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    void getUserSubscriptionChanges()
      .then((data) => setItems(data.results))
      .catch((value) => setError(userMessage(value)));
  }, []);

  if (error) return <Alert type="error" showIcon message={error} />;
  if (!items) return <Spin description="正在加载套餐变更记录" />;

  return (
    <Card title="套餐变更记录">
      <List
        dataSource={items}
        locale={{ emptyText: "暂时没有套餐变更记录。申请或调整套餐后，可在这里查看进度。" }}
        renderItem={(item) => (
          <List.Item>
            <List.Item.Meta
              title={
                <>
                  <Typography.Text>{item.target_plan_name}</Typography.Text>{" "}
                  <Tag>{SUBSCRIPTION_CHANGE_STATUS_LABELS[item.status]}</Tag>
                </>
              }
              description={`调整方式：${SUBSCRIPTION_CHANGE_TYPE_LABELS[item.change_type]}；生效时间：${new Date(item.effective_at).toLocaleString("zh-CN")}`}
            />
          </List.Item>
        )}
      />
    </Card>
  );
}
