"use client";
import { Alert, Button, Card, Input, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { userMessage } from "@/lib/auth-client";
import { getPlans, type Plan } from "@/lib/plans-client";

const statusLabel = { draft: "草稿", published: "已上架", offline: "已下架", archived: "已归档" };
export default function AdminPlansPage() {
  const [plans, setPlans] = useState<Plan[]>([]);
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(
    () =>
      getPlans(status, keyword)
        .then((page) => setPlans(page.results))
        .catch((reason) => setError(userMessage(reason))),
    [keyword, status],
  );
  useEffect(() => {
    void getPlans("", "")
      .then((page) => setPlans(page.results))
      .catch((reason) => setError(userMessage(reason)));
  }, []);
  return (
    <main className="admin-page">
      <Typography.Title>套餐管理</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Space wrap>
          <Input
            aria-label="套餐关键字"
            placeholder="编码或名称"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
          />
          <Select
            aria-label="套餐状态"
            value={status}
            onChange={setStatus}
            style={{ width: 140 }}
            options={[
              { value: "", label: "全部状态" },
              ...Object.entries(statusLabel).map(([value, label]) => ({ value, label })),
            ]}
          />
          <Button onClick={() => void load()}>筛选</Button>
          <Button type="primary" href="/admin/plans/new">
            创建套餐
          </Button>
        </Space>
      </Card>
      <Table
        rowKey="id"
        dataSource={plans}
        pagination={false}
        columns={[
          { title: "编码", dataIndex: "code" },
          { title: "名称", dataIndex: "name" },
          {
            title: "展示价格",
            render: (_, plan) =>
              plan.price_display_mode === "fixed" ? `¥${plan.display_price}` : "联系开通",
          },
          { title: "状态", render: (_, plan) => <Tag>{statusLabel[plan.status]}</Tag> },
          {
            title: "操作",
            render: (_, plan) => <Link href={`/admin/plans/${plan.id}`}>查看</Link>,
          },
        ]}
      />
    </main>
  );
}
