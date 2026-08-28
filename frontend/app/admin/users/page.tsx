"use client";

import { PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  Pagination,
  Select,
  Space,
  Table,
  Tag,
} from "antd";
import type { TableProps } from "antd";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { type AdminUser, type PageData, getAdminUsers, userMessage } from "@/lib/auth-client";

type Filters = { accountStatus?: string; phone?: string };

const accountStatusLabel: Record<string, { text: string; color: string }> = {
  active: { text: "正常", color: "green" },
  frozen: { text: "禁用", color: "orange" },
};

const columns: TableProps<AdminUser>["columns"] = [
  { title: "用户", dataIndex: "nickname" },
  { title: "登录手机号", dataIndex: "phone_masked" },
  { title: "所属管理员", render: () => <span title="请进入详情查看归属管理员">进入详情查看</span> },
  { title: "当前套餐", render: () => <span title="套餐汇总接口待接入">—</span> },
  { title: "剩余额度", render: () => <span title="额度汇总接口待接入">—</span> },
  {
    title: "状态",
    dataIndex: "account_status",
    render: (value: string) => {
      const status = accountStatusLabel[value] ?? { text: "禁用", color: "orange" };
      return <Tag color={status.color}>{status.text}</Tag>;
    },
  },
  {
    title: "测试账号",
    dataIndex: "is_test_account",
    render: (enabled: boolean) => (
      <Tag color={enabled ? "blue" : "default"}>{enabled ? "是" : "否"}</Tag>
    ),
  },
  {
    title: "注册时间",
    dataIndex: "created_at",
    render: (value: string) => new Date(value).toLocaleString("zh-CN"),
  },
  {
    title: "操作",
    render: (_, user) => (
      <Button type="link" href={`/admin/users/${user.id}`}>
        管理
      </Button>
    ),
  },
];

export default function AdminUsersPage() {
  const [form] = Form.useForm<Filters>();
  const [filters, setFilters] = useState<Filters>({});
  const [page, setPage] = useState(1);
  const [data, setData] = useState<PageData<AdminUser> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      setData(await getAdminUsers({ ...filters, page }));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [filters, page]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <div className="admin-page">
      <AdminPageHeader
        title="用户"
        description="查看实际使用显问 GEO 的企业用户，管理账号状态并快速进入详情处理套餐和额度问题。"
        actions={
          <Space wrap>
            <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
              刷新
            </Button>
            <Button type="primary" icon={<PlusOutlined />} disabled title="创建用户接口待接入">
              创建用户
            </Button>
          </Space>
        }
      />
      {error ? <Alert type="error" showIcon title="用户数据加载失败" description={error} /> : null}
      <Card className="admin-surface">
        <Form
          form={form}
          layout="inline"
          onFinish={(values) => {
            setPage(1);
            setFilters(values);
          }}
        >
          <Form.Item
            name="phone"
            label="手机号"
            rules={[{ pattern: /^(?:\+?86)?1[3-9]\d{9}$/, message: "请输入正确的手机号" }]}
          >
            <Input
              allowClear
              prefix={<SearchOutlined />}
              maxLength={14}
              placeholder="按手机号查询"
            />
          </Form.Item>
          <Form.Item name="accountStatus" label="账号状态">
            <Select
              allowClear
              className="admin-filter"
              placeholder="全部状态"
              options={Object.entries(accountStatusLabel).map(([value, status]) => ({
                value,
                label: status.text,
              }))}
            />
          </Form.Item>
          <Button type="primary" htmlType="submit" icon={<SearchOutlined />}>
            查询
          </Button>
        </Form>
      </Card>
      <Card className="admin-surface">
        <Table
          rowKey="id"
          columns={columns}
          dataSource={data?.results ?? []}
          loading={loading}
          pagination={false}
          scroll={{ x: 1050 }}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无用户" />,
          }}
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
    </div>
  );
}
