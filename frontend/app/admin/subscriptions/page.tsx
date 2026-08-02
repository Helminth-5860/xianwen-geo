"use client";

import { Alert, Card, Select, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  getAdminSubscriptions,
  type Subscription,
  type SubscriptionStatus,
} from "@/lib/plans-client";

export default function AdminSubscriptionsPage() {
  const [items, setItems] = useState<Subscription[]>([]);
  const [status, setStatus] = useState<SubscriptionStatus | "">("");
  const [error, setError] = useState("");
  const load = useCallback(
    () =>
      getAdminSubscriptions(status)
        .then((page) => setItems(page.results))
        .catch((reason) => setError(userMessage(reason))),
    [status],
  );
  useEffect(() => void load(), [load]);
  return (
    <main className="admin-page">
      <Typography.Title>订阅管理</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Select
          aria-label="订阅状态"
          value={status}
          onChange={setStatus}
          style={{ width: 180 }}
          options={[
            { value: "", label: "全部状态" },
            { value: "active", label: "生效中" },
            { value: "expired", label: "已到期" },
            { value: "terminated", label: "已终止" },
          ]}
        />
      </Card>
      <Table
        rowKey="id"
        dataSource={items}
        pagination={false}
        columns={[
          { title: "用户", render: (_, item) => item.user_nickname ?? item.user_id },
          { title: "套餐", render: (_, item) => item.plan_name },
          { title: "类型", render: (_, item) => (item.is_trial ? "试用" : "正式") },
          { title: "状态", render: (_, item) => <Tag>{item.status}</Tag> },
          { title: "结束时间", dataIndex: "ends_at" },
          {
            title: "操作",
            render: (_, item) => <Link href={"/admin/subscriptions/" + item.id}>查看</Link>,
          },
        ]}
      />
    </main>
  );
}
