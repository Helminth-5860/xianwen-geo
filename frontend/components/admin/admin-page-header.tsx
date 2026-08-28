import { Space, Typography } from "antd";
import type { ReactNode } from "react";

export function AdminPageHeader({
  title,
  description,
  actions,
}: {
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <div className="admin-page-header">
      <div>
        <Typography.Title level={2}>{title}</Typography.Title>
        <Typography.Paragraph>{description}</Typography.Paragraph>
      </div>
      {actions ? (
        <Space wrap align="center" size="middle" className="admin-page-header__actions">
          {actions}
        </Space>
      ) : null}
    </div>
  );
}
