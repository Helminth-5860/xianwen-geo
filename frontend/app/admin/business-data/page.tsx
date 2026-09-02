"use client";

import {
  FileImageOutlined,
  FileTextOutlined,
  FormOutlined,
  RadarChartOutlined,
  ReadOutlined,
  ReloadOutlined,
  SearchOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Input,
  Pagination,
  Space,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import type { TableProps } from "antd";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { AdminPageHeader } from "@/components/admin/admin-page-header";
import {
  getAdminBusinessData,
  type BusinessDataItem,
  type BusinessDataResource,
  type BusinessDataResult,
} from "@/lib/admin-business-data-client";
import { userMessage } from "@/lib/auth-client";

const resources: ReadonlyArray<{
  key: BusinessDataResource;
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

const statusColor: Record<string, string> = {
  active: "green",
  confirmed: "green",
  generated: "green",
  succeeded: "green",
  ready: "green",
  queued: "blue",
  running: "processing",
  generating: "processing",
  reviewing: "processing",
  partial: "gold",
  draft: "default",
  archived: "default",
  trashed: "default",
  cancelled: "default",
  failed: "red",
  rejected: "red",
};

function displayMetadataValue(value: string | number | boolean | null) {
  if (value === null || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  return String(value);
}

function formatTime(value: string) {
  return new Date(value).toLocaleString("zh-CN");
}

export default function AdminBusinessDataPage() {
  const context = useAdminCapabilities();
  const isSuperuser = context?.commercial_identity === "SUPER_ADMIN";
  const [resource, setResource] = useState<BusinessDataResource>("subjects");
  const [draftQuery, setDraftQuery] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(1);
  const [data, setData] = useState<BusinessDataResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(
    async (signal?: AbortSignal) => {
      if (!isSuperuser) return;
      setLoading(true);
      setError("");
      try {
        setData(
          await getAdminBusinessData({
            resource,
            query,
            page,
            signal,
          }),
        );
      } catch (reason) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setError(userMessage(reason));
      } finally {
        if (!signal?.aborted) setLoading(false);
      }
    },
    [isSuperuser, page, query, resource],
  );

  useEffect(() => {
    if (!isSuperuser) return;
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [isSuperuser, load]);

  const columns = useMemo<TableProps<BusinessDataItem>["columns"]>(
    () => [
      {
        title: "业务数据",
        dataIndex: "title",
        width: 300,
        render: (value: string, item) => (
          <div>
            <Typography.Text strong>{value}</Typography.Text>
            <br />
            <Typography.Text type="secondary" copyable={{ text: item.id }}>
              {item.id}
            </Typography.Text>
          </div>
        ),
      },
      {
        title: "用户",
        width: 190,
        render: (_, item) => (
          <div>
            <Typography.Text strong>{item.user_name || "未命名用户"}</Typography.Text>
            <br />
            <Typography.Text type="secondary">{item.user_phone_masked}</Typography.Text>
            {item.tenant_name ? (
              <>
                <br />
                <Typography.Text type="secondary">{item.tenant_name}</Typography.Text>
              </>
            ) : null}
          </div>
        ),
      },
      {
        title: "主体",
        dataIndex: "subject_name",
        width: 200,
        render: (value: string | null, item) => (
          <div>
            <Typography.Text>{value ?? "—"}</Typography.Text>
            {item.subject_id ? (
              <>
                <br />
                <Typography.Text type="secondary" copyable={{ text: item.subject_id }}>
                  {item.subject_id}
                </Typography.Text>
              </>
            ) : null}
          </div>
        ),
      },
      {
        title: "状态",
        dataIndex: "status_label",
        width: 110,
        render: (value: string, item) => (
          <Tag color={statusColor[item.status] ?? "default"}>{value}</Tag>
        ),
      },
      {
        title: "关键信息",
        width: 330,
        render: (_, item) => {
          const entries = Object.entries(item.metadata).filter(([, value]) => value !== null);
          if (!entries.length) return "—";
          return (
            <Space size={[6, 6]} wrap>
              {entries.slice(0, 6).map(([key, value]) => (
                <Tag key={key}>
                  {key}：{displayMetadataValue(value)}
                </Tag>
              ))}
            </Space>
          );
        },
      },
      {
        title: "更新时间",
        dataIndex: "updated_at",
        width: 180,
        render: (value: string) => formatTime(value),
      },
    ],
    [],
  );

  if (context && !isSuperuser) {
    return (
      <div className="admin-page">
        <AdminPageHeader
          title="业务数据"
          description="全平台业务数据用于跨用户排障，仅超级管理员可访问。"
        />
        <Alert
          type="warning"
          showIcon
          title="仅超级管理员可查看"
          description="普通管理员继续通过用户管理和自己权限范围内的运营页面处理客户问题。"
        />
      </div>
    );
  }

  return (
    <div className="admin-page">
      <AdminPageHeader
        title="业务数据"
        description="集中查询主体、问题、检测任务、报告、文章和图片，在用户遇到问题时快速定位数据。"
        actions={
          <Space wrap>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
              刷新
            </Button>
            <Button disabled>导出查询结果</Button>
          </Space>
        }
      />
      {error ? (
        <Alert
          type="error"
          showIcon
          title="业务数据加载失败"
          description={error}
          style={{ marginBottom: 18 }}
        />
      ) : null}
      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Input.Search
          size="large"
          allowClear
          enterButton="查询"
          prefix={<SearchOutlined />}
          maxLength={120}
          value={draftQuery}
          placeholder="搜索用户、手机号、主体名称、业务数据 ID 或任务编号"
          loading={loading}
          onChange={(event) => setDraftQuery(event.target.value)}
          onSearch={(value) => {
            setPage(1);
            setQuery(value.trim());
            setDraftQuery(value.trim());
          }}
        />
        <Typography.Paragraph type="secondary" style={{ marginBottom: 0, marginTop: 10 }}>
          只读排障查询；不会修改用户数据，也不会展示文章正文、模型原始响应、存储路径或密钥。
        </Typography.Paragraph>
      </Card>
      <div className="admin-resource-grid" aria-label="业务数据分类">
        {resources.map((item) => (
          <div
            className="admin-resource-card"
            key={item.key}
            role="button"
            tabIndex={0}
            aria-pressed={resource === item.key}
            onClick={() => {
              setPage(1);
              setResource(item.key);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                setPage(1);
                setResource(item.key);
              }
            }}
          >
            <span>{item.icon}</span>
            <div>
              <strong>{item.label}</strong>
              <small>{item.description}</small>
            </div>
          </div>
        ))}
      </div>
      <Card className="admin-surface" style={{ marginTop: 18 }}>
        <Tabs
          activeKey={resource}
          onChange={(key) => {
            setPage(1);
            setResource(key as BusinessDataResource);
          }}
          items={resources.map((item) => ({ key: item.key, label: item.label }))}
        />
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data?.items ?? []}
          loading={loading}
          pagination={false}
          scroll={{ x: 1300 }}
          locale={{
            emptyText: (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description={query ? "没有找到匹配的业务数据" : `暂无${resources.find((x) => x.key === resource)?.label ?? "业务"}数据`}
              />
            ),
          }}
        />
        <Pagination
          className="admin-pagination"
          current={page}
          pageSize={data?.page_size ?? 20}
          total={data?.total ?? 0}
          showSizeChanger={false}
          showTotal={(total) => `共 ${total} 条`}
          onChange={setPage}
        />
      </Card>
    </div>
  );
}
