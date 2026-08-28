"use client";

import {
  FileImageOutlined,
  FileTextOutlined,
  FormOutlined,
  RadarChartOutlined,
  ReadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import { Button, Card, Empty, Input, Tabs, Typography } from "antd";
import type { ReactNode } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";

const resources: ReadonlyArray<{
  key: string;
  label: string;
  description: string;
  icon: ReactNode;
}> = [
  { key: "subjects", label: "主体", description: "查看企业主体和基础资料", icon: <ReadOutlined /> },
  {
    key: "questions",
    label: "问题",
    description: "定位用户配置的问题内容",
    icon: <FormOutlined />,
  },
  {
    key: "detections",
    label: "检测任务",
    description: "查询检测进度与执行结果",
    icon: <RadarChartOutlined />,
  },
  {
    key: "reports",
    label: "报告",
    description: "查找已生成的 GEO 报告",
    icon: <FileTextOutlined />,
  },
  {
    key: "articles",
    label: "文章",
    description: "查看内容生成与处理状态",
    icon: <SearchOutlined />,
  },
  {
    key: "images",
    label: "图片",
    description: "查看图片生成与处理状态",
    icon: <FileImageOutlined />,
  },
];

const tablePlaceholder = (label: string) => (
  <Card className="admin-surface">
    <Empty
      image={Empty.PRESENTED_IMAGE_SIMPLE}
      description={
        <div>
          <Typography.Text strong>暂无可展示的{label}数据</Typography.Text>
          <br />
          <Typography.Text type="secondary">全平台查询接口接通后将在这里显示。</Typography.Text>
        </div>
      }
    />
  </Card>
);

export default function AdminBusinessDataPage() {
  return (
    <div className="admin-page">
      <AdminPageHeader
        title="业务数据"
        description="集中查询主体、问题、检测任务和内容结果，在用户遇到问题时快速定位数据。"
        actions={<Button disabled>导出查询结果</Button>}
      />
      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Input
          size="large"
          prefix={<SearchOutlined />}
          placeholder="搜索用户、主体名称或任务编号"
          disabled
          suffix={<Typography.Text type="secondary">查询接口待接入</Typography.Text>}
        />
      </Card>
      <div className="admin-resource-grid" aria-label="业务数据分类">
        {resources.map((resource) => (
          <div className="admin-resource-card" key={resource.key}>
            <span>{resource.icon}</span>
            <div>
              <strong>{resource.label}</strong>
              <small>{resource.description}</small>
            </div>
          </div>
        ))}
      </div>
      <Card className="admin-surface" style={{ marginTop: 18 }}>
        <Tabs
          items={resources.map((resource) => ({
            key: resource.key,
            label: resource.label,
            children: tablePlaceholder(resource.label),
          }))}
        />
      </Card>
    </div>
  );
}
