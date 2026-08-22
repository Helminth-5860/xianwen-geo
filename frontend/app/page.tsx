"use client";

import { ApiOutlined, CheckCircleFilled, CloudServerOutlined } from "@ant-design/icons";
import { Button, Card, ConfigProvider, Space, Tag, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { PlanCatalog } from "@/components/plans/plan-catalog";
import { getCurrentUser } from "@/lib/auth-client";
import { publicEnvironment } from "@/lib/env";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";

const { Paragraph, Text, Title } = Typography;

export default function Home() {
  const router = useRouter();
  useEffect(() => {
    let current = true;
    void getCurrentUser()
      .then((user) => {
        if (current) router.replace(user.home_route);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [router]);

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1668dc", borderRadius: 12 } }}>
      <main className="page-shell">
        <section className="hero">
          <Tag color="blue" icon={<CheckCircleFilled />}>
            显问 GEO 商业工作台
          </Tag>
          <Title>{SITE_NAME}</Title>
          <Paragraph className="hero-description">{SITE_DESCRIPTION}</Paragraph>
          <Space wrap>
            <Button type="primary" href="/register">
              创建账号
            </Button>
            <Button href="/login">用户登录</Button>
            <Button href="/admin/login">管理员登录</Button>
            <Button href="/api/health">检查前端状态</Button>
            <Button href={`${publicEnvironment.apiBaseUrl}/health/`}>检查后端状态</Button>
          </Space>
        </section>

        <section className="status-grid" aria-label="核心能力">
          <Card>
            <ApiOutlined className="card-icon" />
            <Title level={3}>用户工作台</Title>
            <Text>注册后直接进入真实工作台；套餐与额度只控制实际执行，不隐藏功能入口。</Text>
          </Card>
          <Card>
            <CloudServerOutlined className="card-icon" />
            <Title level={3}>租户运营</Title>
            <Text>租户管理员管理本租户用户与业务数据，平台超级管理员保留全局治理能力。</Text>
          </Card>
          <Card>
            <CheckCircleFilled className="card-icon" />
            <Title level={3}>安全边界</Title>
            <Text>敏感操作继续由 RBAC、确认与 SMS Step-Up 保护，数据访问按租户隔离。</Text>
          </Card>
        </section>

        <PlanCatalog />
      </main>
    </ConfigProvider>
  );
}
