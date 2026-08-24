"use client";

import { Alert, Form, Input, Modal, Space, Typography } from "antd";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { createAdminStepUpChallenge, verifyAdminStepUp } from "@/lib/admin-rbac-client";
import { setAdminStepUpHandler, userMessage } from "@/lib/auth-client";

type PendingVerification = {
  promise: Promise<void>;
  resolve: () => void;
  reject: (reason: Error) => void;
};

export function AdminStepUpProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const [challengeId, setChallengeId] = useState("");
  const [smsCode, setSmsCode] = useState("");
  const [remaining, setRemaining] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = useRef<PendingVerification | null>(null);

  const requestStepUp = useCallback(async () => {
    if (pending.current) return pending.current.promise;
    setBusy(true);
    setError("");
    try {
      const challenge = await createAdminStepUpChallenge();
      setChallengeId(challenge.challenge_id);
      setRemaining(challenge.expires_in);
      setSmsCode("");
      setOpen(true);
    } catch (reason) {
      setError(userMessage(reason));
      throw reason;
    } finally {
      setBusy(false);
    }
    let resolve!: () => void;
    let reject!: (reason: Error) => void;
    const promise = new Promise<void>((resolvePromise, rejectPromise) => {
      resolve = resolvePromise;
      reject = rejectPromise;
    });
    pending.current = { promise, resolve, reject };
    return promise;
  }, []);

  useEffect(() => {
    setAdminStepUpHandler(requestStepUp);
    return () => {
      setAdminStepUpHandler(null);
      pending.current?.reject(new Error("安全验证页面已关闭"));
      pending.current = null;
    };
  }, [requestStepUp]);

  useEffect(() => {
    if (!open || remaining <= 0) return;
    const timer = window.setInterval(() => setRemaining((value) => Math.max(0, value - 1)), 1000);
    return () => window.clearInterval(timer);
  }, [open, remaining]);

  const close = (reason: string) => {
    pending.current?.reject(new Error(reason));
    pending.current = null;
    setOpen(false);
    setChallengeId("");
    setSmsCode("");
    setRemaining(0);
    setError("");
  };

  const verify = async () => {
    if (!challengeId || !/^\d{6}$/.test(smsCode) || busy || remaining <= 0) {
      setError(remaining <= 0 ? "验证码已过期，请重新执行操作" : "请输入 6 位短信验证码");
      return;
    }
    setBusy(true);
    setError("");
    try {
      await verifyAdminStepUp(challengeId, smsCode);
      const current = pending.current;
      pending.current = null;
      setOpen(false);
      setChallengeId("");
      setSmsCode("");
      setRemaining(0);
      current?.resolve();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {children}
      <Modal
        title="高风险操作安全验证"
        open={open}
        okText="验证并继续"
        cancelText="取消操作"
        confirmLoading={busy}
        okButtonProps={{ disabled: remaining <= 0 }}
        onOk={() => void verify()}
        onCancel={() => !busy && close("已取消安全验证")}
        mask={{ closable: false }}
        destroyOnHidden
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert
            type={remaining > 0 ? "info" : "warning"}
            showIcon
            title={
              remaining > 0
                ? `验证码已发送，将在 ${remaining} 秒后过期`
                : "验证码已过期，请取消后重新执行操作"
            }
          />
          <Form.Item label="短信验证码" required style={{ marginBottom: 0 }}>
            <Input
              aria-label="高风险操作短信验证码"
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={smsCode}
              onChange={(event) => setSmsCode(event.target.value.replace(/\D/g, ""))}
            />
          </Form.Item>
          <Typography.Text type="secondary">
            验证仅保存在当前管理员服务器 Session 中，短时有效；页面刷新不会自动发送短信。
          </Typography.Text>
          {error && <Alert type="error" showIcon title={error} />}
        </Space>
      </Modal>
    </>
  );
}
