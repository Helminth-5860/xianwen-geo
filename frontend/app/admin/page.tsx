"use client";

import { Card, Typography } from "antd";

import { useAdminCapabilities } from "@/components/admin/admin-capability";

export default function AdminDashboardPage() {
  const context = useAdminCapabilities();
  return (
    <main className="auth-shell">
      <Card>
        <Typography.Title level={2}>后台工作台</Typography.Title>
        <Typography.Text>
          {context?.nickname}，当前客户数据范围为 {context?.data_scope}。
        </Typography.Text>
      </Card>
    </main>
  );
}
