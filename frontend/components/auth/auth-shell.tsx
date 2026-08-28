import { ArrowLeftOutlined } from "@ant-design/icons";
import { Button, Card, Space, Typography } from "antd";
import Link from "next/link";
import type { ReactNode } from "react";

import { SITE_NAME } from "@/lib/site";

const { Paragraph, Text, Title } = Typography;

export function AuthShell({
  eyebrow,
  title,
  description,
  children,
  footer,
}: Readonly<{
  eyebrow: string;
  title: string;
  description: string;
  children: ReactNode;
  footer: ReactNode;
}>) {
  return (
    <main className="auth-page">
      <section className="auth-intro" aria-labelledby="auth-title">
        <Link href="/" className="auth-back-link">
          <ArrowLeftOutlined aria-hidden /> 返回首页
        </Link>
        <Text className="auth-eyebrow">{eyebrow}</Text>
        <Title id="auth-title">{title}</Title>
        <Paragraph>{description}</Paragraph>
        <Text type="secondary">{SITE_NAME} 会安全保护你的登录信息。</Text>
      </section>
      <Card className="auth-card" bordered={false}>
        <Space direction="vertical" size={24} className="auth-card-content">
          {children}
          <div className="auth-footer">{footer}</div>
        </Space>
      </Card>
    </main>
  );
}

export function SubmitButton({ children, loading }: { children: ReactNode; loading: boolean }) {
  return (
    <Button type="primary" htmlType="submit" loading={loading} block size="large">
      {children}
    </Button>
  );
}
