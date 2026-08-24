"use client";

import { Alert, Button, Input, Modal, Space, Typography } from "antd";
import { useState, type ReactNode } from "react";

import { userMessage } from "@/lib/auth-client";
import type { RiskMode } from "@/lib/risk-client";

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
  execute: (credentials: RiskCredentials) => Promise<T>;
  onExecuted: (result: T) => void;
}>;

const modeText: Record<RiskMode, string> = {
  confirm: "确认后立即执行",
  password: "需要当前登录密码再次验证",
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
      onExecuted(result);
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
        okText="确认执行"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={() => !submitting && setOpen(false)}
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert type="info" showIcon title={modeText[mode]} />
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
          {error && <Alert type="error" showIcon title={error} />}
        </Space>
      </Modal>
    </>
  );
}
