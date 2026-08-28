"use client";

import { SearchOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Form, Input, InputNumber, Modal, Space, Table } from "antd";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  adjustQuotaAccount,
  getAdminQuotaAccounts,
  type QuotaAccount,
  type QuotaAdjustmentAction,
} from "@/lib/quota-client";

const labels: Record<QuotaAdjustmentAction, string> = {
  grant: "增加额度",
  compensate: "补充额度",
  "manual-deduct": "扣减额度",
};

export default function AdminQuotasPage() {
  const capabilities = useAdminCapabilities();
  const canAdjust = capabilities?.permission_keys.includes("quotas.adjust") ?? false;
  const [items, setItems] = useState<QuotaAccount[]>([]);
  const [keyword, setKeyword] = useState("");
  const [error, setError] = useState("");
  const [resultMessage, setResultMessage] = useState("");
  const [selected, setSelected] = useState<QuotaAccount | null>(null);
  const [action, setAction] = useState<QuotaAdjustmentAction>("grant");
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<{ amount: number; reason: string }>();

  const load = useCallback(
    () =>
      getAdminQuotaAccounts()
        .then((page) => setItems(page.results))
        .catch((reason) => setError(userMessage(reason))),
    [],
  );

  useEffect(() => void load(), [load]);

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
      await load();
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
        title="额度管理"
        description="查看用户额度，执行增加、扣减和补充操作；所有调整都会自动进入操作记录。"
      />
      {error ? <Alert type="error" showIcon title={error} /> : null}
      {resultMessage ? (
        <Alert
          type="success"
          showIcon
          title="额度调整完成"
          description="最新额度已经刷新，本次操作也已写入操作记录。"
        />
      ) : null}
      {!canAdjust ? <Alert type="warning" showIcon title="当前账号没有额度调整权限" /> : null}
      <Card className="admin-surface">
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索用户名"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          style={{ maxWidth: 360, marginBottom: 18 }}
        />
        <Table
          rowKey="id"
          dataSource={items.filter((item) => item.user_nickname.includes(keyword.trim()))}
          pagination={false}
          locale={{
            emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无额度记录" />,
          }}
          columns={[
            { title: "用户", dataIndex: "user_nickname" },
            { title: "当前套餐", render: () => <span title="套餐汇总接口待接入">—</span> },
            { title: "额度类型", dataIndex: "quota_type" },
            { title: "当前额度", dataIndex: "entitlement_amount" },
            { title: "剩余额度", dataIndex: "available" },
            { title: "累计消耗", render: () => <span title="消耗汇总接口待接入">—</span> },
            { title: "最近调整", render: () => <span title="最近调整接口待接入">—</span> },
            {
              title: "操作",
              render: (_, account) =>
                canAdjust ? (
                  <Space wrap>
                    {(Object.keys(labels) as QuotaAdjustmentAction[]).map((key) => (
                      <Button key={key} aria-label={labels[key]} onClick={() => open(account, key)}>
                        {labels[key]}
                      </Button>
                    ))}
                    <Button disabled title="重置接口待接入">
                      重置额度
                    </Button>
                  </Space>
                ) : null,
            },
          ]}
        />
      </Card>
      <Modal
        open={Boolean(selected)}
        title="额度调整"
        okText="确认调整"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={() => setSelected(null)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="amount"
            label="调整数量"
            rules={[{ required: true }, { type: "number", min: 1 }]}
          >
            <InputNumber min={1} precision={0} />
          </Form.Item>
          <Form.Item
            name="reason"
            label="调整原因"
            rules={[{ required: true, message: "请填写调整原因" }]}
          >
            <Input maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
