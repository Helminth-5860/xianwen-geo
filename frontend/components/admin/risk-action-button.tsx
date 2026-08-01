"use client";

import { Alert, Button, Input, Modal, Space, Typography } from "antd";
import { useState, type ReactNode } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  isApprovalCreated,
  type ApprovalCreated,
  type RiskExecution,
  type RiskMode,
} from "@/lib/risk-client";

export type RiskCredentials = Readonly<{
  confirmed: true;
  current_password: string;
  reason: string;
}>;

type Props<T> = Readonly<{
  actionName: string;
  mode: RiskMode;
  danger?: boolean;
  disabled?: boolean;
  reasonRequired?: boolean;
  children: ReactNode;
  execute: (credentials: RiskCredentials) => Promise<RiskExecution<T>>;
  onExecuted: (result: T) => void;
  onApproval: (approval: ApprovalCreated) => void;
}>;

const modeText: Record<RiskMode, string> = {
  confirm: "确认后立即执行",
  password: "需要当前登录密码再次验证",
  two_person: "提交后由另一名有效超级管理员审批，当前不会执行",
};

export function RiskActionButton<T>({
  actionName,
  mode,
  danger,
  disabled,
  reasonRequired = false,
  children,
  execute,
  onExecuted,
  onApproval,
}: Props<T>) {
  const [open, setOpen] = useState(false);
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const submit = async () => {
    if (submitting) return;
    if (mode === "password" && !password) {
      setError("请输入当前登录密码");
      return;
    }
    if (reasonRequired && !reason.trim()) {
      setError("请填写操作原因");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      const result = await execute({
        confirmed: true,
        current_password: mode === "password" ? password : "",
        reason: reason.trim(),
      });
      if (isApprovalCreated(result)) onApproval(result);
      else onExecuted(result);
      setPassword("");
      setReason("");
      setOpen(false);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <Button danger={danger} disabled={disabled} onClick={() => setOpen(true)}>
        {children}
      </Button>
      <Modal
        title={actionName}
        open={open}
        okText={mode === "two_person" ? "发起审批" : "确认执行"}
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={() => !submitting && setOpen(false)}
      >
        <Space direction="vertical" style={{ width: "100%" }}>
          <Alert
            type={mode === "two_person" ? "warning" : "info"}
            showIcon
            message={modeText[mode]}
            description={
              mode === "two_person"
                ? "如果没有第二名当前有效超级管理员，服务端会拒绝创建请求。"
                : undefined
            }
          />
          {reasonRequired && (
            <label>
              <Typography.Text>操作原因</Typography.Text>
              <Input.TextArea
                aria-label="操作原因"
                value={reason}
                maxLength={500}
                onChange={(event) => setReason(event.target.value)}
              />
            </label>
          )}
          {mode === "password" && (
            <label>
              <Typography.Text>当前登录密码</Typography.Text>
              <Input.Password
                aria-label="当前登录密码"
                value={password}
                autoComplete="current-password"
                onChange={(event) => setPassword(event.target.value)}
              />
            </label>
          )}
          {error && <Alert type="error" showIcon message={error} />}
        </Space>
      </Modal>
    </>
  );
}
