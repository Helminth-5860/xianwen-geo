"use client";

import {
  Alert,
  Button,
  Card,
  Form,
  Input,
  InputNumber,
  Modal,
  Space,
  Table,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  adjustQuotaAccount,
  getAdminQuotaAccounts,
  type QuotaAccount,
  type QuotaAdjustmentAction,
} from "@/lib/quota-client";

import { isApprovalCreated } from "@/lib/risk-client";
const labels: Record<QuotaAdjustmentAction, string> = {
  grant: "\u8d60\u9001",
  compensate: "\u8865\u507f",
  "manual-deduct": "\u4eba\u5de5\u6263\u51cf",
};

export default function AdminQuotasPage() {
  const capabilities = useAdminCapabilities();
  const canAdjust = capabilities?.permission_keys.includes("quotas.adjust") ?? false;
  const [items, setItems] = useState<QuotaAccount[]>([]);
  const [error, setError] = useState("");
  const [approval, setApproval] = useState("");
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
    setApproval("");
    form.resetFields();
  };
  const submit = async () => {
    if (!selected) return;
    try {
      const values = await form.validateFields();
      setSubmitting(true);
      setError("");
      const result = await adjustQuotaAccount(
        selected.id,
        action,
        selected.version,
        values.amount,
        values.reason,
        crypto.randomUUID(),
      );
      setApproval(isApprovalCreated(result) ? result.approval_id : "");
      setSelected(null);
    } catch (reason) {
      if (reason && typeof reason === "object" && "errorFields" in reason) return;
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className="admin-page">
      <Typography.Title>{"\u989d\u5ea6\u7ba1\u7406"}</Typography.Title>
      {error && <Alert type="error" showIcon title={error} />}
      {approval && (
        <Alert
          type="info"
          showIcon
          title={"\u5df2\u53d1\u8d77\u53cc\u4eba\u5ba1\u6279"}
          description={approval}
        />
      )}
      {!canAdjust && (
        <Alert
          type="warning"
          showIcon
          title={"\u5f53\u524d\u8d26\u53f7\u6ca1\u6709\u989d\u5ea6\u8c03\u6574\u6743\u9650"}
        />
      )}
      <Card>
        <Table
          rowKey="id"
          dataSource={items}
          pagination={false}
          columns={[
            { title: "\u7528\u6237", dataIndex: "user_nickname" },
            { title: "\u989d\u5ea6\u7c7b\u578b", dataIndex: "quota_type" },
            { title: "\u6743\u76ca\u989d\u5ea6", dataIndex: "entitlement_amount" },
            { title: "\u53ef\u7528", dataIndex: "available" },
            { title: "\u51bb\u7ed3", dataIndex: "frozen" },
            {
              title: "\u64cd\u4f5c",
              render: (_, account) =>
                canAdjust ? (
                  <Space>
                    {(Object.keys(labels) as QuotaAdjustmentAction[]).map((key) => (
                      <Button key={key} aria-label={labels[key]} onClick={() => open(account, key)}>
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
        title={"\u989d\u5ea6\u8c03\u6574\uff08\u56fa\u5b9a\u53cc\u4eba\u5ba1\u6279\uff09"}
        okText={"\u53d1\u8d77\u5ba1\u6279"}
        cancelText={"\u53d6\u6d88"}
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={() => setSelected(null)}
      >
        <Form form={form} layout="vertical">
          <Form.Item
            name="amount"
            label={"\u8c03\u6574\u6570\u91cf"}
            rules={[{ required: true }, { type: "number", min: 1 }]}
          >
            <InputNumber min={1} precision={0} />
          </Form.Item>
          <Form.Item
            name="reason"
            label={"\u8c03\u6574\u539f\u56e0"}
            rules={[{ required: true, message: "\u8bf7\u586b\u5199\u8c03\u6574\u539f\u56e0" }]}
          >
            <Input maxLength={500} />
          </Form.Item>
        </Form>
      </Modal>
    </main>
  );
}
