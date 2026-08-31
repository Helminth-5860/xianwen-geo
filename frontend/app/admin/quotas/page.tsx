"use client";

import { SearchOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Form,
  Input,
  InputNumber,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  adjustQuotaAccount,
  CUSTOMER_QUOTA_PRESENTATION,
  CUSTOMER_QUOTA_TYPES,
  customerQuotaPresentation,
  customerQuotaType,
  getAdminQuotaAccounts,
  type QuotaAccount,
  type QuotaAdjustmentAction,
} from "@/lib/quota-client";

const labels: Record<QuotaAdjustmentAction, string> = {
  grant: "增加额度",
  "manual-deduct": "扣减额度",
  compensate: "补发额度",
  refund: "返还额度",
};

function formatDate(value?: string | null) {
  if (!value) return "暂无";
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function AdminQuotasPage() {
  const capabilities = useAdminCapabilities();
  const canAdjust = capabilities?.permission_keys.includes("quotas.adjust") ?? false;
  const [items, setItems] = useState<QuotaAccount[]>([]);
  const [keyword, setKeyword] = useState("");
  const [quotaType, setQuotaType] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [resultMessage, setResultMessage] = useState("");
  const [selected, setSelected] = useState<QuotaAccount | null>(null);
  const [action, setAction] = useState<QuotaAdjustmentAction>("grant");
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<{ amount: number; reason: string }>();

  const load = useCallback(
    async (nextPage = 1) => {
      setLoading(true);
      setError("");
      try {
        const result = await getAdminQuotaAccounts(nextPage, quotaType, keyword);
        setItems(result.results.filter((item) => customerQuotaType(item.quota_type) !== null));
        setPage(result.pagination.page);
        setTotal(result.pagination.count);
      } catch (reason) {
        setError(userMessage(reason));
      } finally {
        setLoading(false);
      }
    },
    [keyword, quotaType],
  );

  useEffect(() => {
    void getAdminQuotaAccounts()
      .then((result) => {
        setItems(result.results.filter((item) => customerQuotaType(item.quota_type) !== null));
        setPage(result.pagination.page);
        setTotal(result.pagination.count);
      })
      .catch((reason) => setError(userMessage(reason)));
  }, []);

  const open = (account: QuotaAccount, nextAction: QuotaAdjustmentAction) => {
    setSelected(account);
    setAction(nextAction);
    setResultMessage("");
    form.resetFields();
  };

  const submit = async () => {
    if (!selected) return;
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      setError("");
      await adjustQuotaAccount(
        selected.id,
        action,
        selected.version,
        values.amount,
        values.reason,
        crypto.randomUUID(),
      );
      setResultMessage("额度已调整并记录");
      setSelected(null);
      await load(page);
    } catch (reason) {
      if (reason && typeof reason === "object" && "errorFields" in reason) return;
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="admin-page">
      <AdminPageHeader
        title="客户额度中心"
        description="按客户和套餐查看自然额度，人工调整会保留完整记录。"
      />
      {error ? <Alert type="error" showIcon title={error} /> : null}
      {resultMessage ? (
        <Alert
          type="success"
          showIcon
          title="额度调整完成"
          description="最新额度已经刷新，本次调整也已记录。"
        />
      ) : null}
      {!canAdjust ? <Alert type="warning" showIcon title="当前账号没有额度调整权限" /> : null}
      <Card className="admin-surface">
        <Space wrap style={{ marginBottom: 18 }}>
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="搜索客户名称"
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            onPressEnter={() => void load(1)}
            style={{ width: 260 }}
          />
          <Select
            aria-label="额度功能"
            value={quotaType}
            style={{ width: 210 }}
            options={[
              { value: "", label: "全部功能" },
              ...CUSTOMER_QUOTA_TYPES.map((value) => ({
                value,
                label: CUSTOMER_QUOTA_PRESENTATION[value].name,
              })),
            ]}
            onChange={setQuotaType}
          />
          <Button type="primary" onClick={() => void load(1)}>
            查询
          </Button>
        </Space>
        <Table<QuotaAccount>
          rowKey="id"
          loading={loading}
          dataSource={items}
          scroll={{ x: 1120 }}
          pagination={{
            current: page,
            pageSize: 20,
            total,
            showSizeChanger: false,
            onChange: (nextPage) => void load(nextPage),
          }}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无客户额度" />,
          }}
          columns={[
            { title: "客户", dataIndex: "user_nickname", width: 150 },
            {
              title: "当前套餐",
              render: (_, item) => item.subscription_plan_name ?? item.plan_name ?? "未命名套餐",
              width: 150,
            },
            {
              title: "功能",
              render: (_, item) => customerQuotaPresentation(item.quota_type)?.name ?? "套餐额度",
              width: 150,
            },
            {
              title: "已使用",
              render: (_, item) => {
                const value = Math.max(
                  0,
                  item.used_amount ?? item.entitlement_amount - item.available - item.frozen,
                );
                return `${value} ${customerQuotaPresentation(item.quota_type)?.unit ?? ""}`;
              },
              width: 110,
            },
            {
              title: "总额度",
              render: (_, item) =>
                `${item.total_amount ?? item.entitlement_amount} ${customerQuotaPresentation(item.quota_type)?.unit ?? ""}`,
              width: 110,
            },
            {
              title: "剩余",
              render: (_, item) => (
                <Tag color={item.available === 0 ? "red" : "blue"}>
                  {item.available} {customerQuotaPresentation(item.quota_type)?.unit ?? ""}
                </Tag>
              ),
              width: 110,
            },
            {
              title: "最近调整",
              render: (_, item) => formatDate(item.last_adjustment?.created_at ?? item.last_ledger_created_at),
              width: 170,
            },
            {
              title: "操作",
              fixed: "right",
              width: 320,
              render: (_, account) =>
                canAdjust ? (
                  <Space wrap size={4}>
                    {(Object.keys(labels) as QuotaAdjustmentAction[]).map((key) => (
                      <Button
                        key={key}
                        size="small"
                        aria-label={labels[key]}
                        onClick={() => open(account, key)}
                      >
                        {labels[key]}
                      </Button>
                    ))}
                  </Space>
                ) : null,
            },
          ]}
        />
      </Card>
      <Modal
        open={Boolean(selected)}
        title={
          selected
            ? `${labels[action]} · ${customerQuotaPresentation(selected.quota_type)?.name ?? "套餐额度"}`
            : "额度调整"
        }
        okText="确认调整"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={() => setSelected(null)}
      >
        {selected ? (
          <Typography.Paragraph type="secondary">
            当前剩余 {selected.available}{" "}
            {customerQuotaPresentation(selected.quota_type)?.unit ?? ""}
          </Typography.Paragraph>
        ) : null}
        <Form form={form} layout="vertical">
          <Form.Item
            name="amount"
            label="调整数量"
            rules={[
              { required: true, message: "请填写调整数量" },
              { type: "number", min: 1 },
            ]}
          >
            <InputNumber min={1} precision={0} style={{ width: "100%" }} />
          </Form.Item>
          <Form.Item
            name="reason"
            label="调整原因"
            rules={[{ required: true, message: "请填写调整原因" }]}
          >
            <Input.TextArea
              maxLength={500}
              rows={3}
              placeholder="请说明本次调整原因，便于后续查阅"
            />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
