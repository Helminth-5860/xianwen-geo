"use client";

import { PlusOutlined, ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Form, Input, Modal, Select, Space, Table, Tag } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { useAdminCapabilities } from "@/components/admin/admin-capability";
import {
  createAdmin,
  getAdmins,
  getRoles,
  getTenants,
  type AdminProfile,
  type Role,
  type Tenant,
} from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";

type CreateAdminForm = Readonly<{
  phone: string;
  nickname: string;
  password: string;
  companyId: string;
}>;

const statusLabel = {
  active: { text: "正常", color: "green" },
  disabled: { text: "已停用", color: "default" },
  locked: { text: "已锁定", color: "orange" },
} as const;

export default function AdminAccountsPage() {
  const capabilities = useAdminCapabilities();
  const canCreate = capabilities?.permission_keys.includes("admins.create") ?? false;
  const [admins, setAdmins] = useState<AdminProfile[]>([]);
  const [roles, setRoles] = useState<Role[]>([]);
  const [companies, setCompanies] = useState<Tenant[]>([]);
  const [keyword, setKeyword] = useState("");
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [adminPage, rolePage, companyRows] = await Promise.all([
        getAdmins(),
        getRoles(),
        getTenants(),
      ]);
      setAdmins(adminPage.results);
      setRoles(rolePage.results.filter((item) => item.status === "active"));
      setCompanies(companyRows.filter((item) => item.status === "active"));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const visibleAdmins = useMemo(() => {
    const query = keyword.trim();
    if (!query) return admins;
    return admins.filter((admin) =>
      `${admin.nickname} ${admin.phone_masked} ${admin.tenant_name ?? ""}`.includes(query),
    );
  }, [admins, keyword]);

  const submit = async (values: CreateAdminForm) => {
    if (roles.length !== 1) {
      setError("平台标准管理权限尚未唯一配置，暂时无法创建管理员。");
      return;
    }
    const [standardAccess] = roles;
    setSubmitting(true);
    setError("");
    try {
      await createAdmin({
        phone: values.phone,
        nickname: values.nickname,
        password: values.password,
        role_id: standardAccess.id,
        tenant_id: values.companyId,
      });
      setOpen(false);
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="admin-page">
      <AdminPageHeader
        title="管理员"
        description="管理企业侧的管理账号，查看所属公司、账号状态并进入详情执行启停等操作。"
        actions={
          <Space wrap>
            <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
              刷新
            </Button>
            {canCreate ? (
              <Button type="primary" icon={<PlusOutlined />} onClick={() => setOpen(true)}>
                创建管理员
              </Button>
            ) : null}
          </Space>
        }
      />
      {error ? <Alert type="error" showIcon title={error} style={{ marginBottom: 18 }} /> : null}
      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索管理员、手机号或公司名称"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          style={{ maxWidth: 420 }}
        />
      </Card>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={visibleAdmins}
        pagination={{ pageSize: 15, hideOnSinglePage: true }}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无管理员" />,
        }}
        columns={[
          { title: "管理员", dataIndex: "nickname" },
          { title: "登录手机号", dataIndex: "phone_masked" },
          {
            title: "公司名称",
            render: (_, item) => (item.is_superuser ? "显问平台" : item.tenant_name || "尚未设置"),
          },
          {
            title: "当前套餐",
            render: (_, item) =>
              item.is_superuser ? "不适用" : <span title="套餐汇总接口待接入">—</span>,
          },
          {
            title: "账号类型",
            render: (_, item) =>
              item.is_superuser ? (
                <Tag color="purple">超级管理员</Tag>
              ) : (
                <Tag color="blue">管理员</Tag>
              ),
          },
          {
            title: "状态",
            render: (_, item) => (
              <Tag color={statusLabel[item.admin_status].color}>
                {statusLabel[item.admin_status].text}
              </Tag>
            ),
          },
          {
            title: "操作",
            render: (_, item) => (
              <Button type="link" href={`/admin/admins/${item.id}`}>
                管理
              </Button>
            ),
          },
        ]}
      />

      <Modal
        title="创建管理员"
        open={open}
        footer={null}
        onCancel={() => setOpen(false)}
        destroyOnHidden
      >
        <Alert
          type="info"
          showIcon
          title="新账号将使用平台标准管理权限，创建后可立即登录后台。"
          style={{ marginBottom: 18 }}
        />
        <Form
          layout="vertical"
          onFinish={(values) => void submit(values as CreateAdminForm)}
          disabled={submitting}
        >
          <Form.Item
            name="phone"
            label="登录手机号"
            rules={[{ required: true, message: "请输入登录手机号" }]}
          >
            <Input autoComplete="tel" />
          </Form.Item>
          <Form.Item
            name="nickname"
            label="管理员名称"
            rules={[{ required: true, message: "请输入管理员名称" }]}
          >
            <Input />
          </Form.Item>
          <Form.Item
            name="companyId"
            label="公司名称"
            rules={[{ required: true, message: "请选择所属公司" }]}
          >
            <Select
              showSearch
              optionFilterProp="label"
              options={companies.map((company) => ({
                value: company.id,
                label: company.display_name,
              }))}
              placeholder="选择管理员所属公司"
            />
          </Form.Item>
          <Form.Item
            name="password"
            label="初始密码"
            rules={[{ required: true, min: 12, message: "请输入至少 12 位初始密码" }]}
          >
            <Input.Password autoComplete="new-password" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={submitting} block>
            确认创建
          </Button>
        </Form>
      </Modal>
    </div>
  );
}
