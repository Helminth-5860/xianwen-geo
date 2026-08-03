"use client";

import { Alert, Card, Select, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  getAdminSubscriptionChanges,
  type SubscriptionChange,
  type SubscriptionChangeStatus,
} from "@/lib/plans-client";

export default function AdminSubscriptionChangesPage() {
  const [items, setItems] = useState<SubscriptionChange[]>([]);
  const [status, setStatus] = useState<SubscriptionChangeStatus | "">("");
  const [error, setError] = useState("");
  const load = useCallback(
    () =>
      getAdminSubscriptionChanges(status)
        .then((page) => setItems(page.results))
        .catch((value) => setError(userMessage(value))),
    [status],
  );
  useEffect(() => void load(), [load]);
  return (
    <main className="admin-page">
      <Typography.Title>套餐变更</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Select
          aria-label="套餐变更状态"
          value={status}
          onChange={setStatus}
          style={{ width: 180 }}
          options={[
            { value: "", label: "全部状态" },
            { value: "scheduled", label: "已排期" },
            { value: "executed", label: "已执行" },
            { value: "cancelled", label: "已取消" },
          ]}
        />
      </Card>
      <Table
        rowKey="id"
        dataSource={items}
        pagination={false}
        columns={[
          { title: "用户", render: (_, item) => item.user_nickname ?? item.user_id },
          { title: "目标套餐", dataIndex: "target_plan_name" },
          { title: "类型", dataIndex: "change_type" },
          { title: "状态", render: (_, item) => <Tag>{item.status}</Tag> },
          { title: "生效时间", dataIndex: "effective_at" },
          {
            title: "操作",
            render: (_, item) => <Link href={`/admin/subscription-changes/${item.id}`}>查看</Link>,
          },
        ]}
      />
    </main>
  );
}
