"use client";

import { Alert, Button, Card, Input, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getAdminPlanApplications, type AdminPlanApplication } from "@/lib/plans-client";

export default function AdminPlanApplicationsPage() {
  const [items, setItems] = useState<AdminPlanApplication[]>([]);
  const [status, setStatus] = useState("");
  const [planId, setPlanId] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(
    () =>
      getAdminPlanApplications(status, planId)
        .then((page) => setItems(page.results))
        .catch((reason) => setError(userMessage(reason))),
    [planId, status],
  );
  useEffect(() => void load(), [load]);
  return (
    <main className="admin-page">
      <Typography.Title>套餐申请管理</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Space wrap>
          <Select
            aria-label="申请状态"
            value={status}
            onChange={setStatus}
            style={{ width: 160 }}
            options={[
              { value: "", label: "全部状态" },
              { value: "pending", label: "待处理" },
              { value: "contacted", label: "已联系" },
              { value: "closed", label: "已关闭" },
              { value: "cancelled", label: "已取消" },
            ]}
          />
          <Input
            aria-label="套餐 ID"
            value={planId}
            onChange={(event) => setPlanId(event.target.value)}
          />
          <Button onClick={() => void load()}>筛选</Button>
        </Space>
      </Card>
      <Table
        rowKey="id"
        dataSource={items}
        pagination={false}
        columns={[
          { title: "申请编号", dataIndex: "id" },
          {
            title: "用户",
            render: (_, item) => `${item.applicant_nickname} ${item.applicant_phone_masked}`,
          },
          {
            title: "套餐版本",
            render: (_, item) => `${item.plan_id} / v${item.requested_version_no}`,
          },
          { title: "状态", render: (_, item) => <Tag>{item.status}</Tag> },
          { title: "负责人", render: (_, item) => item.current_owner?.nickname ?? "未分配" },
          {
            title: "操作",
            render: (_, item) => <Link href={`/admin/plan-applications/${item.id}`}>查看</Link>,
          },
        ]}
      />
    </main>
  );
}
