"use client";

import { ApiOutlined, CheckCircleFilled, CloudServerOutlined } from "@ant-design/icons";
import { Button, Card, ConfigProvider, Space, Tag, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";

import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";
import { publicEnvironment } from "@/lib/env";

const { Paragraph, Text, Title } = Typography;

export default function Home() {
  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1668dc", borderRadius: 12 } }}>
      <main className="page-shell">
        <section className="hero">
          <Tag color="blue" icon={<CheckCircleFilled />}>
            XW-0001 工程基础已就绪
          </Tag>
          <Title>{SITE_NAME}</Title>
          <Paragraph className="hero-description">{SITE_DESCRIPTION}</Paragraph>
          <Space wrap>
            <Button type="primary" href="/api/health">
              检查前端状态
            </Button>
            <Button href={`${publicEnvironment.apiBaseUrl}/health/`}>检查后端状态</Button>
          </Space>
        </section>

        <section className="status-grid" aria-label="工程组件">
          <Card>
            <ApiOutlined className="card-icon" />
            <Title level={3}>前端</Title>
            <Text>Next.js、TypeScript 与 Ant Design 已完成基础集成。</Text>
          </Card>
          <Card>
            <CloudServerOutlined className="card-icon" />
            <Title level={3}>后端</Title>
            <Text>Django、DRF 与 Celery 已具备健康检查和任务队列基础。</Text>
          </Card>
          <Card>
            <CheckCircleFilled className="card-icon" />
            <Title level={3}>基础设施</Title>
            <Text>Docker Compose 统一编排 PostgreSQL、Redis 和应用服务。</Text>
          </Card>
        </section>
      </main>
    </ConfigProvider>
  );
}
