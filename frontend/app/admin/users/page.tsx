"use client";

import { ArrowLeftOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  Pagination,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import type { TableProps } from "antd";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";

import { type AdminUser, type PageData, getAdminUsers, userMessage } from "@/lib/auth-client";

const { Title } = Typography;

type Filters = {
  approvalStatus?: string;
  accountStatus?: string;
  phone?: string;
};

const columns: TableProps<AdminUser>["columns"] = [
  { title: "昵称", dataIndex: "nickname" },
  { title: "手机号", dataIndex: "phone_masked" },
  {
    title: "审核状态",
    dataIndex: "approval_status",
    render: (value: string) => (
      <Tag color={value === "approved" ? "green" : value === "rejected" ? "red" : "blue"}>
        {value === "approved" ? "已通过" : value === "rejected" ? "已拒绝" : "待审核"}
      </Tag>
    ),
  },
  {
    title: "账号状态",
    dataIndex: "account_status",
    render: (value: string) => <Tag>{value}</Tag>,
  },
  {
    title: "注册时间",
    dataIndex: "created_at",
    render: (value: string) => new Date(value).toLocaleString("zh-CN"),
  },
  {
    title: "操作",
    key: "action",
    render: (_, user) => (
      <Button type="link" href={`/admin/users/${user.id}`}>
        查看与审核
      </Button>
    ),
  },
];

export default function AdminUsersPage() {
  const [form] = Form.useForm<Filters>();
  const [filters, setFilters] = useState<Filters>({ approvalStatus: "pending" });
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PageData<AdminUser> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const capabilities = useAdminCapabilities();
  const canReview = Boolean(capabilities?.permission_keys.includes("users.review"));
  const canFreeze = Boolean(capabilities?.permission_keys.includes("users.freeze"));

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getAdminUsers({ ...filters, page }));
    } catch (loadError) {
      setError(userMessage(loadError));
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const submit = (values: Filters) => {
    setPage(1);
    setFilters(values);
  };

  return (
    <main className="admin-page">
      <Button type="link" href="/" icon={<ArrowLeftOutlined />}>
        返回首页
      </Button>
      <Space className="admin-title" align="center">
        <Title>用户审核</Title>
        <Button icon={<ReloadOutlined />} onClick={() => void load()}>
          刷新
        </Button>
      </Space>
      {error && <Alert type="error" showIcon message="无法加载审核数据" description={error} />}
      {(!canReview || !canFreeze) && (
        <Alert
          type="info"
          showIcon
          message="部分用户管理操作不可用"
          description={
            !canReview && !canFreeze
              ? "当前账号没有用户审核和账号冻结权限。"
              : !canReview
                ? "当前账号没有用户审核权限。"
                : "当前账号没有账号冻结权限。"
          }
        />
      )}
      <Card>
        <Form
          form={form}
          layout="inline"
          initialValues={{ approvalStatus: "pending" }}
          onFinish={submit}
        >
          <Form.Item name="approvalStatus" label="审核状态">
            <Select
              allowClear
              className="admin-filter"
              options={[
                { value: "pending", label: "待审核" },
                { value: "approved", label: "已通过" },
                { value: "rejected", label: "已拒绝" },
              ]}
            />
          </Form.Item>
          <Form.Item name="accountStatus" label="账号状态">
            <Select
              allowClear
              className="admin-filter"
              options={[
                { value: "active", label: "正常" },
                { value: "frozen", label: "冻结" },
                { value: "cancel_pending", label: "注销冷静期" },
                { value: "cancelled", label: "已注销" },
              ]}
            />
          </Form.Item>
          <Form.Item
            name="phone"
            label="完整手机号"
            rules={[{ pattern: /^(?:\+?86)?1[3-9]\d{9}$/, message: "请输入完整手机号" }]}
          >
            <Input allowClear maxLength={14} placeholder="仅精确匹配" />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
            查询
          </Button>
        </Form>
      </Card>
      <Card>
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data?.results ?? []}
          loading={loading}
          pagination={false}
          scroll={{ x: 880 }}
        />
        <Pagination
          className="admin-pagination"
          current={page}
          pageSize={data?.pagination.page_size ?? 20}
          total={data?.pagination.count ?? 0}
          showSizeChanger={false}
          onChange={setPage}
        />
      </Card>
    </main>
  );
}
