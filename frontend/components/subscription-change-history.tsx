"use client";

import { Alert, Card, List, Spin, Tag, Typography } from "antd";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getUserSubscriptionChanges, type SubscriptionChange } from "@/lib/plans-client";

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
        locale={{ emptyText: "暂无套餐变更记录" }}
        renderItem={(item) => (
          <List.Item>
            <List.Item.Meta
              title={
                <>
                  <Typography.Text>{item.target_plan_name}</Typography.Text>{" "}
                  <Tag>{item.status}</Tag>
                </>
              }
              description={`变更类型：${item.change_type}；生效时间：${item.effective_at}`}
            />
          </List.Item>
        )}
      />
    </Card>
  );
}
