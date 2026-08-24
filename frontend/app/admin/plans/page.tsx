"use client";
import { Alert, Button, Card, Empty, Input, Select, Space, Table, Tag } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { userMessage } from "@/lib/auth-client";
import { getPlans, type Plan } from "@/lib/plans-client";
import { AdminPageHeader } from "@/components/admin/admin-page-header";

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
      <AdminPageHeader
        title="套餐管理"
        description="统一维护套餐价格、功能权益、使用额度和可用模型，并查看套餐当前状态。"
        actions={
          <Button type="primary" href="/admin/plans/new">
            创建套餐
          </Button>
        }
      />
      {error && <Alert type="error" showIcon title={error} />}
      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Space wrap>
          <Button href="/admin/subscriptions">用户套餐</Button>
          <Button href="/admin/plan-applications">开通申请</Button>
          <Button href="/admin/subscription-changes">套餐调整记录</Button>
        </Space>
      </Card>
      <Card className="admin-surface">
        <Space wrap>
          <Input
            aria-label="套餐关键字"
            placeholder="搜索套餐名称"
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
        </Space>
      </Card>
      <Card className="admin-surface">
        <Table
          rowKey="id"
          dataSource={plans}
          pagination={false}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无套餐" />,
          }}
          columns={[
            { title: "套餐名称", dataIndex: "name" },
            {
              title: "套餐价格",
              render: (_, plan) =>
                plan.price_display_mode === "fixed" ? `¥${plan.display_price}` : "联系开通",
            },
            { title: "套餐说明", dataIndex: "description", ellipsis: true },
            { title: "功能权限", render: () => "进入详情查看" },
            { title: "使用额度", render: () => "进入详情查看" },
            { title: "状态", render: (_, plan) => <Tag>{statusLabel[plan.status]}</Tag> },
            {
              title: "操作",
              render: (_, plan) => <Link href={`/admin/plans/${plan.id}`}>管理</Link>,
            },
          ]}
        />
      </Card>
    </main>
  );
}
