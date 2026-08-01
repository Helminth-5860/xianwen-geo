"use client";

import { Alert, Button, Card, Descriptions, List, Space, Spin, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  cancelPlanApplication,
  getPlanApplication,
  type PlanApplication,
} from "@/lib/plans-client";

export default function PlanApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [item, setItem] = useState<PlanApplication | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    void getPlanApplication(id)
      .then((application) => {
        if (current) setItem(application);
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      });
    return () => {
      current = false;
    };
  }, [id]);
  if (error) return <Alert type="error" showIcon message={error} />;
  if (!item) return <Spin description="正在加载申请" />;
  const open = item.status === "pending" || item.status === "contacted";
  return (
    <main className="page-shell">
      <Typography.Title>套餐申请详情</Typography.Title>
      <Card>
        <Descriptions column={1}>
          <Descriptions.Item label="申请编号">{item.id}</Descriptions.Item>
          <Descriptions.Item label="套餐">
            {String(item.public_plan_snapshot.name)}
          </Descriptions.Item>
          <Descriptions.Item label="绑定版本">第 {item.requested_version_no} 版</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag>{item.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="申请备注">{item.user_note || "无"}</Descriptions.Item>
        </Descriptions>
        <Space>
          <Button href="/plan-applications">返回列表</Button>
          {open && (
            <Button
              danger
              onClick={() =>
                void cancelPlanApplication(item.id, item.version)
                  .then(setItem)
                  .catch((reason) => setError(userMessage(reason)))
              }
            >
              取消申请
            </Button>
          )}
        </Space>
      </Card>
      <Card title="状态历史">
        <List
          dataSource={item.events}
          renderItem={(event) => <List.Item>{event.safe_summary}</List.Item>}
        />
      </Card>
    </main>
  );
}
