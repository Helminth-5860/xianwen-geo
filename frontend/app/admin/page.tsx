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
          {context?.nickname}，当前身份为 {context?.commercial_identity}；数据范围为
          {context?.commercial_identity === "PLATFORM_SUPER_ADMIN"
            ? "全平台"
            : context?.tenant_name || "当前租户"}
          。
        </Typography.Text>
      </Card>
    </main>
  );
}
