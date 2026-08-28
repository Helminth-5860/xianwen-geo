"use client";

import { Card, Empty, Typography } from "antd";

const { Paragraph, Text, Title } = Typography;

type DataCenterPlaceholderProps = Readonly<{
  title: string;
  description: string;
  emptyDescription: string;
}>;

export function DataCenterPlaceholder({
  title,
  description,
  emptyDescription,
}: DataCenterPlaceholderProps) {
  return (
    <main className="geo-dashboard">
      <section className="geo-dashboard__header">
        <div>
          <Text type="secondary">数据中心</Text>
          <Title level={2}>{title}</Title>
          <Paragraph type="secondary">{description}</Paragraph>
        </div>
      </section>

      <Card className="geo-dashboard__empty">
        <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description={emptyDescription} />
      </Card>
    </main>
  );
}
