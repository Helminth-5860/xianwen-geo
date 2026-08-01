"use client";

import { Alert, Button, Card, Descriptions, Input, Modal, Space, Tag, Typography } from "antd";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  approveApproval,
  cancelApproval,
  getApproval,
  rejectApproval,
  type Approval,
} from "@/lib/risk-client";

export default function ApprovalDetailPage() {
  const { id } = useParams<{ id: string }>();
  const context = useAdminCapabilities();
  const [approval, setApproval] = useState<Approval | null>(null);
  const [error, setError] = useState("");
  const [password, setPassword] = useState("");
  const [reason, setReason] = useState("");
  const load = useCallback(() => {
    void getApproval(id)
      .then(setApproval)
      .catch((value) => setError(userMessage(value)));
  }, [id]);
  useEffect(load, [load]);
  const act = async (operation: () => Promise<Approval>) => {
    try {
      setApproval(await operation());
      setError("");
      setPassword("");
      setReason("");
    } catch (value) {
      setError(userMessage(value));
    }
  };
  if (!approval) return <Alert type={error ? "error" : "info"} message={error || "正在加载审批"} />;
  const pending = approval.status === "pending";
  const requester = approval.requester_id === context?.user_id;
  const canApprove =
    pending &&
    !requester &&
    Boolean(context?.is_superuser) &&
    Boolean(context?.permission_keys.includes("approvals.approve"));
  const canReject =
    pending &&
    !requester &&
    Boolean(context?.is_superuser) &&
    Boolean(context?.permission_keys.includes("approvals.reject"));
  const canCancel =
    pending && requester && Boolean(context?.permission_keys.includes("approvals.cancel"));
  return (
    <main className="admin-page">
      <Button href="/admin/approvals">返回审批列表</Button>
      <Typography.Title>审批详情</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Descriptions bordered column={1}>
          <Descriptions.Item label="请求编号">{approval.id}</Descriptions.Item>
          <Descriptions.Item label="动作">{approval.action_key}</Descriptions.Item>
          <Descriptions.Item label="目标">{approval.safe_summary}</Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag>{approval.status}</Tag>
          </Descriptions.Item>
          <Descriptions.Item label="过期时间">
            {new Date(approval.expires_at).toLocaleString("zh-CN")}
          </Descriptions.Item>
          {approval.stable_error_code && (
            <Descriptions.Item label="稳定错误码">{approval.stable_error_code}</Descriptions.Item>
          )}
        </Descriptions>
        <Space direction="vertical" style={{ width: "100%", marginTop: 16 }}>
          {canApprove && (
            <>
              <Input.Password
                aria-label="审批当前密码"
                value={password}
                autoComplete="current-password"
                placeholder="输入当前登录密码后批准并同步执行"
                onChange={(event) => setPassword(event.target.value)}
              />
              <Button
                type="primary"
                disabled={!password}
                onClick={() => void act(() => approveApproval(id, password))}
              >
                批准并执行
              </Button>
            </>
          )}
          {canReject && (
            <>
              <Input.TextArea
                aria-label="拒绝原因"
                value={reason}
                maxLength={500}
                placeholder="填写安全的拒绝原因"
                onChange={(event) => setReason(event.target.value)}
              />
              <Button
                danger
                disabled={!reason.trim()}
                onClick={() => void act(() => rejectApproval(id, reason))}
              >
                拒绝
              </Button>
            </>
          )}
          {canCancel && (
            <Button
              onClick={() =>
                Modal.confirm({
                  title: "确认取消本人发起的审批？",
                  onOk: () => act(() => cancelApproval(id)),
                })
              }
            >
              取消请求
            </Button>
          )}
          {pending && requester && (
            <Alert type="info" showIcon message="发起人不能批准或拒绝自己的请求" />
          )}
        </Space>
      </Card>
    </main>
  );
}
