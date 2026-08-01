"use client";

import { ApiOutlined, CheckCircleFilled, CloudServerOutlined } from "@ant-design/icons";
import { Alert, Button, Card, ConfigProvider, Space, Tag, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useSyncExternalStore } from "react";
import { PlanCatalog } from "@/components/plans/plan-catalog";

import { publicEnvironment } from "@/lib/env";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";

const { Paragraph, Text, Title } = Typography;

export default function Home() {
  const pendingAccount = useSyncExternalStore(
    () => () => undefined,
    () => new URLSearchParams(window.location.search).get("account") === "pending",
    () => false,
  );

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1668dc", borderRadius: 12 } }}>
      <main className="page-shell">
        {pendingAccount && (
          <Alert
            className="account-status-alert"
            type="info"
            showIcon
            message="账号待审核"
            description="你已成功登录。审核通过前可以查看系统说明，后续主体资料功能将按任务逐步开放。"
          />
        )}
        <section className="hero">
          <Tag color="blue" icon={<CheckCircleFilled />}>
            账号与认证基础已就绪
          </Tag>
          <Title>{SITE_NAME}</Title>
          <Paragraph className="hero-description">{SITE_DESCRIPTION}</Paragraph>
          <Space wrap>
            <Button type="primary" href="/register">
              创建账号
            </Button>
            <Button href="/login">登录</Button>
            <Button href="/api/health">检查前端状态</Button>
            <Button href={`${publicEnvironment.apiBaseUrl}/health/`}>检查后端状态</Button>
          </Space>
        </section>

        <section className="status-grid" aria-label="工程组件">
          <Card>
            <ApiOutlined className="card-icon" />
            <Title level={3}>安全认证</Title>
            <Text>支持密码和短信验证码登录，使用 HttpOnly Session 与真实 CSRF 防护。</Text>
          </Card>
          <Card>
            <CloudServerOutlined className="card-icon" />
            <Title level={3}>后端</Title>
            <Text>Django、DRF 与 Celery 已具备统一错误、日志和任务队列基础。</Text>
          </Card>
          <Card>
            <CheckCircleFilled className="card-icon" />
            <Title level={3}>基础设施</Title>
            <Text>Docker Compose 统一编排 PostgreSQL、Redis 和应用服务。</Text>
          </Card>
        </section>

        <PlanCatalog />
      </main>
    </ConfigProvider>
  );
}
