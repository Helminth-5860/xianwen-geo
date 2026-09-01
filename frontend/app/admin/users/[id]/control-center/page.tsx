"use client";

import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button } from "antd";
import { useParams } from "next/navigation";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { UserControlCenter } from "@/components/admin/user-control-center";

export default function AdminUserControlCenterPage() {
  const params = useParams<{ id: string }>();
  const userId = params.id;

  return (
    <main className="admin-page">
      <AdminPageHeader
        title="用户控制中心"
        description="查看并管理该用户的真实套餐、业务额度、使用情况、安全归属与审计证据。"
        actions={
          <Button href={`/admin/users/${userId}`} icon={<ArrowLeftOutlined />}>
            返回原用户详情
          </Button>
        }
      />
      <UserControlCenter userId={userId} />
    </main>
  );
}
