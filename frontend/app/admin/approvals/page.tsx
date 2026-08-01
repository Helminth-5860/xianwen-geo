"use client";

import { Alert, Button, Card, Pagination, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage, type PageData } from "@/lib/auth-client";
import { getApprovals, type Approval } from "@/lib/risk-client";

export default function ApprovalListPage() {
  const context = useAdminCapabilities();
  const [data, setData] = useState<PageData<Approval> | null>(null);
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      setData(await getApprovals(page, status));
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [page, status]);
  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);
  return (
    <main className="admin-page">
      <Typography.Title>高风险审批</Typography.Title>
      <Alert
        type="info"
        showIcon
        message={context?.is_superuser ? "可查看全部请求和待我审批" : "仅显示我发起的请求"}
      />
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Space direction="vertical" style={{ width: "100%" }}>
          <Select
            aria-label="审批状态"
            value={status}
            onChange={(value) => {
              setPage(1);
              setStatus(value);
            }}
            options={[
              { value: "", label: "全部状态" },
              { value: "pending", label: "待审批" },
              { value: "executed", label: "已执行" },
              { value: "rejected", label: "已拒绝" },
              { value: "cancelled", label: "已取消" },
              { value: "expired", label: "已过期" },
              { value: "stale", label: "已失效" },
              { value: "execution_failed", label: "执行失败" },
            ]}
          />
          <Table
            rowKey="id"
            pagination={false}
            dataSource={data?.results ?? []}
            columns={[
              { title: "动作", dataIndex: "action_key" },
              { title: "目标摘要", dataIndex: "safe_summary" },
              { title: "状态", dataIndex: "status", render: (value) => <Tag>{value}</Tag> },
              {
                title: "过期时间",
                dataIndex: "expires_at",
                render: (value) => new Date(value).toLocaleString("zh-CN"),
              },
              {
                title: "操作",
                render: (_, item) => (
                  <Link href={`/admin/approvals/${item.id}`}>
                    <Button type="link">查看</Button>
                  </Link>
                ),
              },
            ]}
          />
          <Pagination
            current={page}
            pageSize={data?.pagination.page_size ?? 20}
            total={data?.pagination.count ?? 0}
            showSizeChanger={false}
            onChange={setPage}
          />
        </Space>
      </Card>
    </main>
  );
}
