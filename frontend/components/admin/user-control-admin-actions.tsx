"use client";

import { Alert, Button, Card, Input, Modal, Space, Spin, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { useAdminCapabilities } from "./admin-capability";
import { CustomerAssignmentActions } from "./customer-assignment-actions";
import { SubscriptionChangeAction } from "./subscription-change-action";
import { UserStatusActions } from "./user-status-actions";
import {
  getAdmins,
  getCustomerAssignment,
  type AdminProfile,
  type CustomerAssignment,
} from "@/lib/admin-rbac-client";
import { getAdminUserControlCenter } from "@/lib/admin-user-control-client";
import {
  freezeAdminUser,
  getAdminUser,
  unfreezeAdminUser,
  userMessage,
  type AdminUser,
} from "@/lib/auth-client";
import {
  getAdminSubscription,
  terminateSubscription,
  type Subscription,
} from "@/lib/plans-client";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";

const { Paragraph, Text } = Typography;

type Props = Readonly<{
  userId: string;
  onChanged?: () => void | Promise<void>;
}>;

export function UserControlAdminActions({ userId, onChanged }: Props) {
  const capabilities = useAdminCapabilities();
  const [user, setUser] = useState<AdminUser | null>(null);
  const [assignment, setAssignment] = useState<CustomerAssignment | null>(null);
  const [admins, setAdmins] = useState<AdminProfile[]>([]);
  const [subscription, setSubscription] = useState<Subscription | null>(null);
  const [riskModes, setRiskModes] = useState<Record<string, RiskMode>>({});
  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [terminateOpen, setTerminateOpen] = useState(false);
  const [terminateReason, setTerminateReason] = useState("");

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    try {
      const [currentUser, controlCenter, actions] = await Promise.all([
        getAdminUser(userId),
        getAdminUserControlCenter(userId),
        getRiskActions(),
      ]);
      setUser(currentUser);
      setRiskModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));

      if (controlCenter.subscription) {
        setSubscription(await getAdminSubscription(controlCenter.subscription.id));
      } else {
        setSubscription(null);
      }

      const canAssign = Boolean(capabilities?.permission_keys.includes("users.assign"));
      if (canAssign) {
        const [assignmentData, adminPage] = await Promise.all([
          getCustomerAssignment(userId),
          capabilities?.permission_keys.includes("admins.list")
            ? getAdmins()
            : Promise.resolve(null),
        ]);
        setAssignment(assignmentData);
        setAdmins(adminPage?.results ?? []);
      } else {
        setAssignment(null);
        setAdmins([]);
      }
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [capabilities, userId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const notifyChanged = async () => {
    await load();
    await onChanged?.();
  };

  const unfreeze = async () => {
    if (submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await unfreezeAdminUser(userId);
      setSuccess("用户账号已恢复，真实账号状态已立即生效。");
      await notifyChanged();
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const terminate = async () => {
    if (!subscription || submitting) return;
    const reason = terminateReason.trim();
    if (!reason) {
      setError("请填写终止套餐原因。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      await terminateSubscription(subscription.id, subscription.version, reason);
      setTerminateOpen(false);
      setTerminateReason("");
      setSuccess("用户当前套餐已终止，套餐状态与实际业务权限已同步更新。");
      await notifyChanged();
    } catch (value) {
      setError(userMessage(value));
    } finally {
      setSubmitting(false);
    }
  };

  if (loading && !user) {
    return (
      <Card size="small">
        <Spin description="正在加载管理员控制项" />
      </Card>
    );
  }

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      {error ? <Alert type="error" showIcon title={error} closable onClose={() => setError("")} /> : null}
      {success ? (
        <Alert type="success" showIcon title={success} closable onClose={() => setSuccess("")} />
      ) : null}

      <Card title="账号控制" size="small">
        <Paragraph type="secondary">
          这里调用现有账号风控链路，不直接修改数据库。禁用、恢复都会立即影响用户真实账号状态。
        </Paragraph>
        {user ? (
          <UserStatusActions
            user={user}
            submitting={submitting}
            freezeMode={riskModes["user.freeze"] ?? "confirm"}
            executeFreeze={(credentials) =>
              freezeAdminUser(userId, user.status_version, credentials)
            }
            onRiskExecuted={() => {
              setSuccess("用户账号已禁用，真实账号状态已立即生效。");
              void notifyChanged();
            }}
            onUnfreeze={() => void unfreeze()}
          />
        ) : null}
      </Card>

      {capabilities?.permission_keys.includes("users.assign") && assignment ? (
        <CustomerAssignmentActions
          key={`${assignment.customer_id}:${assignment.version}:${assignment.owner_admin_id}`}
          assignment={assignment}
          admins={admins}
          mode={riskModes["customer.assignment.change"] ?? "password"}
          onChanged={(changed) => {
            setAssignment(changed);
            setSuccess("用户归属已更新，后端数据隔离与管理员可见范围将按新归属生效。");
            void notifyChanged();
          }}
        />
      ) : null}

      <Card title="套餐控制" size="small">
        {subscription ? (
          <Space orientation="vertical" size={12} style={{ width: "100%" }}>
            <Text>
              当前套餐：{subscription.plan_name} V{subscription.plan_version_no} · 状态 {subscription.status}
            </Text>
            <Space wrap>
              <SubscriptionChangeAction
                subscription={subscription}
                onCompleted={() => {
                  setSuccess("套餐变更已提交/执行，用户实际订阅与额度将按现有套餐变更规则处理。");
                  void notifyChanged();
                }}
                onError={setError}
              />
              {subscription.status === "active" &&
              capabilities?.permission_keys.includes("subscriptions.terminate") ? (
                <Button danger onClick={() => setTerminateOpen(true)}>
                  终止当前套餐
                </Button>
              ) : null}
            </Space>
          </Space>
        ) : (
          <Alert
            type="info"
            showIcon
            title="当前没有生效套餐"
            description="本控制中心不会通过测试账号或人工试用入口制造虚假权益。正式套餐开通继续使用现有套餐申请/开通链路，待注册免费体验自动发放逻辑完成后会直接反映在这里。"
          />
        )}
      </Card>

      <Modal
        title="确认终止当前套餐"
        open={terminateOpen}
        okText="确认终止"
        cancelText="取消"
        okButtonProps={{ danger: true, disabled: !terminateReason.trim() }}
        confirmLoading={submitting}
        onCancel={() => {
          if (submitting) return;
          setTerminateOpen(false);
          setTerminateReason("");
        }}
        onOk={() => void terminate()}
      >
        <Space orientation="vertical" size={12} style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title="终止后会立即改变用户真实套餐状态，并写入现有风险/操作记录链路。"
          />
          <Input.TextArea
            value={terminateReason}
            onChange={(event) => setTerminateReason(event.target.value)}
            rows={3}
            maxLength={500}
            showCount
            placeholder="请输入终止原因"
          />
        </Space>
      </Modal>
    </Space>
  );
}
