"use client";

import {
  Alert,
  Button,
  Card,
  Col,
  Descriptions,
  Empty,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  adjustControlCenterQuota,
  getAdminUserControlCenter,
  type AdminUserControlCenter,
  type ControlCenterAuditEntry,
  type ControlCenterLedgerEntry,
  type ControlCenterLoginEvent,
  type ControlCenterPlanLimit,
  type ControlCenterQuota,
  type ControlCenterQuotaAccount,
  type ControlCenterSubscription,
} from "@/lib/admin-user-control-client";
import { userMessage } from "@/lib/auth-client";

const { Paragraph, Text, Title } = Typography;

type AdjustmentMode = "increase" | "deduct" | "target";
type AdjustmentForm = { amount: string; reason: string };

const ledgerActionLabels: Record<string, string> = {
  initialize: "套餐额度到账",
  freeze: "任务处理中",
  consume: "业务消耗",
  release: "额度退回",
  grant: "管理员增加",
  compensate: "额度补充",
  refund: "额度返还",
  manual_deduct: "管理员扣减",
  plan_change_forfeit: "套餐变更清零",
  plan_change_transfer_out: "套餐变更转出",
  plan_change_transfer_in: "套餐变更转入",
  cycle_forfeit: "周期额度更新",
  expiry_forfeit: "套餐到期调整",
};

const auditActionLabels: Record<string, string> = {
  "user.freeze": "禁用用户",
  "customer.assignment.change": "修改用户归属",
  "quota.grant": "增加额度",
  "quota.compensate": "补充额度",
  "quota.manual_deduct": "扣减额度",
  "subscription.open": "开通套餐",
  "subscription.terminate": "终止套餐",
  "subscription.change": "变更套餐",
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

function parseAmount(value: string | null | undefined) {
  try {
    return BigInt(value || "0");
  } catch {
    return 0n;
  }
}

function formatAmount(value: string | null | undefined) {
  const amount = parseAmount(value);
  return new Intl.NumberFormat("zh-CN").format(amount);
}

function formatSignedAmount(value: string | null | undefined) {
  const amount = parseAmount(value);
  if (amount === 0n) return "0";
  return `${amount > 0n ? "+" : ""}${new Intl.NumberFormat("zh-CN").format(amount)}`;
}

function formatLimitValue(limit: ControlCenterPlanLimit) {
  const { value } = limit;
  if (value === null || value === undefined) return "不限 / 未设置";
  if (typeof value === "boolean") return value ? "开启" : "关闭";
  if (typeof value === "number" || typeof value === "bigint") {
    return `${new Intl.NumberFormat("zh-CN").format(value)}${limit.unit ? ` ${limit.unit}` : ""}`;
  }
  if (typeof value === "string") return value || "未设置";
  return JSON.stringify(value, null, 2);
}

function accountLabel(account: ControlCenterQuotaAccount, index: number) {
  const type = account.batch_type === "primary" ? "套餐基础账户" : "结转/附加账户";
  return `${type} ${index + 1} · 可用 ${formatAmount(account.available)}`;
}

function sourceLabel(source: string, isTrial: boolean) {
  if (isTrial) return "注册体验 / 试用";
  const labels: Record<string, string> = {
    application: "套餐申请",
    plan_change: "套餐变更",
    trial_grant: "试用",
  };
  return labels[source] ?? source;
}

function statusTag(status: string) {
  const active = status === "active";
  return <Tag color={active ? "green" : "orange"}>{active ? "正常" : "禁用"}</Tag>;
}

function subscriptionStatusTag(status: string) {
  const labels: Record<string, string> = {
    active: "生效中",
    expired: "已到期",
    terminated: "已终止",
  };
  return <Tag color={status === "active" ? "green" : "default"}>{labels[status] ?? status}</Tag>;
}

function QuotaAccountBreakdown({ quota }: { quota: ControlCenterQuota }) {
  return (
    <Table<ControlCenterQuotaAccount>
      rowKey="id"
      size="small"
      pagination={false}
      dataSource={[...quota.accounts]}
      columns={[
        {
          title: "账户类型",
          render: (_, account) =>
            account.batch_type === "primary" ? "套餐基础账户" : "结转 / 附加账户",
        },
        {
          title: "套餐基准",
          render: (_, account) => `${formatAmount(account.entitlement_amount)} ${quota.unit_display_name}`,
        },
        {
          title: "已使用",
          render: (_, account) => `${formatAmount(account.used_amount)} ${quota.unit_display_name}`,
        },
        {
          title: "处理中",
          render: (_, account) => `${formatAmount(account.frozen)} ${quota.unit_display_name}`,
        },
        {
          title: "当前可用",
          render: (_, account) => `${formatAmount(account.available)} ${quota.unit_display_name}`,
        },
        {
          title: "有效至",
          render: (_, account) => formatDate(account.spendable_until ?? account.cycle_ends_at),
        },
        { title: "版本", dataIndex: "version", width: 80 },
      ]}
    />
  );
}

export function UserControlCenter({ userId }: { userId: string }) {
  const [data, setData] = useState<AdminUserControlCenter | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [activeTab, setActiveTab] = useState("overview");
  const [selectedQuota, setSelectedQuota] = useState<ControlCenterQuota | null>(null);
  const [selectedAccountId, setSelectedAccountId] = useState("");
  const [adjustmentMode, setAdjustmentMode] = useState<AdjustmentMode>("increase");
  const [submitting, setSubmitting] = useState(false);
  const [form] = Form.useForm<AdjustmentForm>();

  const load = useCallback(async () => {
    if (!userId) return;
    setLoading(true);
    setError("");
    try {
      setData(await getAdminUserControlCenter(userId));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [userId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const selectedAccount = useMemo(
    () => selectedQuota?.accounts.find((account) => account.id === selectedAccountId) ?? null,
    [selectedAccountId, selectedQuota],
  );

  const openAdjustment = (quota: ControlCenterQuota) => {
    const account =
      quota.accounts.find((item) => item.adjustable && item.batch_type === "primary") ??
      quota.accounts.find((item) => item.adjustable);
    if (!account) {
      setError("该项目当前没有可人工调整的额度账户。");
      return;
    }
    setSelectedQuota(quota);
    setSelectedAccountId(account.id);
    setAdjustmentMode("increase");
    setSuccess("");
    form.resetFields();
  };

  const closeAdjustment = () => {
    if (submitting) return;
    setSelectedQuota(null);
    setSelectedAccountId("");
    form.resetFields();
  };

  const submitAdjustment = async () => {
    if (!selectedQuota || !selectedAccount) return;
    try {
      const values = await form.validateFields();
      if (!/^\d+$/.test(values.amount)) {
        form.setFields([{ name: "amount", errors: ["请输入整数额度"] }]);
        return;
      }
      const requested = BigInt(values.amount);
      const current = BigInt(selectedAccount.available);
      let delta = requested;
      let action: "grant" | "manual-deduct" = adjustmentMode === "deduct" ? "manual-deduct" : "grant";

      if (adjustmentMode === "target") {
        delta = requested - current;
        if (delta === 0n) {
          form.setFields([{ name: "amount", errors: ["目标余额与当前余额相同，无需调整"] }]);
          return;
        }
        action = delta < 0n ? "manual-deduct" : "grant";
        if (delta < 0n) delta = -delta;
      }
      if (delta <= 0n) {
        form.setFields([{ name: "amount", errors: ["调整数量必须大于 0"] }]);
        return;
      }
      setSubmitting(true);
      setError("");
      await adjustControlCenterQuota({
        accountId: selectedAccount.id,
        accountVersion: selectedAccount.version,
        action,
        amount: delta.toString(),
        reason: values.reason,
        idempotencyKey: crypto.randomUUID(),
      });
      setSuccess(`${selectedQuota.display_name}额度已调整，用户实际可用额度已同步更新。`);
      closeAdjustment();
      await load();
    } catch (reason) {
      if (reason && typeof reason === "object" && "errorFields" in reason) return;
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  if (!data && loading) {
    return <Card loading title="用户控制中心" />;
  }

  if (!data) {
    return <Alert type="error" showIcon title={error || "无法读取用户控制中心"} />;
  }

  const policyLimits = data.plan_limits.filter((limit) => !limit.quota_type);
  const modelRows = data.model_permissions.map((item, index) => ({
    key: String(item.model_key ?? index),
    model_key: String(item.model_key ?? "未知模型"),
    selected_by_default: Boolean(item.selected_by_default),
    sort_order: Number(item.sort_order ?? index),
  }));

  const overview = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Row gutter={[16, 16]}>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="当前套餐" value={data.subscription?.plan_name ?? "无生效套餐"} />
            <Text type="secondary">
              {data.subscription ? `V${data.subscription.plan_version_no}` : "未绑定有效订阅"}
            </Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="当前额度项目" value={data.quotas.length} suffix="项" />
            <Text type="secondary">全部来自真实 QuotaAccount</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="所属代理 / 管理员" value={data.user.assignment?.owner_name || "平台直管"} />
            <Text type="secondary">{data.user.assignment?.owner_role || "无代理归属"}</Text>
          </Card>
        </Col>
        <Col xs={24} sm={12} lg={6}>
          <Card size="small">
            <Statistic title="最近登录" value={formatDate(data.user.login.last_success_at)} />
            <Text type="secondary">IP：{data.user.login.last_success_ip || "暂无"}</Text>
          </Card>
        </Col>
      </Row>

      <Card title="完整账户信息" size="small">
        <Descriptions bordered column={{ xs: 1, md: 2, xl: 3 }}>
          <Descriptions.Item label="用户 ID">{data.user.id}</Descriptions.Item>
          <Descriptions.Item label="昵称">{data.user.nickname}</Descriptions.Item>
          <Descriptions.Item label="手机号">{data.user.phone_masked}</Descriptions.Item>
          <Descriptions.Item label="账号状态">{statusTag(data.user.account_status)}</Descriptions.Item>
          <Descriptions.Item label="注册时间">{formatDate(data.user.created_at)}</Descriptions.Item>
          <Descriptions.Item label="资料更新时间">{formatDate(data.user.updated_at)}</Descriptions.Item>
          <Descriptions.Item label="所属租户">
            {data.user.tenant?.display_name || "未绑定租户"}
          </Descriptions.Item>
          <Descriptions.Item label="租户标识">{data.user.tenant?.key || "—"}</Descriptions.Item>
          <Descriptions.Item label="所属代理 / 管理员">
            {data.user.assignment?.owner_name || "平台直管"}
          </Descriptions.Item>
          <Descriptions.Item label="代理角色">
            {data.user.assignment?.owner_role || "—"}
          </Descriptions.Item>
          <Descriptions.Item label="最近登录 IP">
            {data.user.login.last_success_ip || "暂无"}
          </Descriptions.Item>
          <Descriptions.Item label="最近登录设备" span={2}>
            {data.user.login.last_success_user_agent || "暂无"}
          </Descriptions.Item>
        </Descriptions>
      </Card>

      <Card title="核心额度摘要" size="small">
        {data.quotas.length ? (
          <Row gutter={[12, 12]}>
            {data.quotas.map((quota) => (
              <Col xs={24} sm={12} lg={8} xl={6} key={quota.quota_type}>
                <Card size="small">
                  <Text type="secondary">{quota.display_name}</Text>
                  <Title level={4} style={{ margin: "6px 0" }}>
                    {formatAmount(quota.available)} {quota.unit_display_name}
                  </Title>
                  <Text type="secondary">
                    套餐 {formatAmount(quota.entitlement_amount)} · 人工调整 {formatSignedAmount(quota.manual_adjustment_amount)}
                  </Text>
                </Card>
              </Col>
            ))}
          </Row>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有生效额度" />
        )}
      </Card>
    </Space>
  );

  const entitlements = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Alert
        type="info"
        showIcon
        title="这里展示并调整用户当前真实业务额度"
        description="管理员调整直接写入 Quota Ledger；用户端余额和业务接口使用同一份额度账户，不存在后台改了但用户端不生效的第二套数据。"
      />
      <Table<ControlCenterQuota>
        rowKey="quota_type"
        dataSource={[...data.quotas]}
        pagination={false}
        scroll={{ x: 1150 }}
        expandable={{ expandedRowRender: (quota) => <QuotaAccountBreakdown quota={quota} /> }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无额度" /> }}
        columns={[
          { title: "项目", dataIndex: "display_name", fixed: "left", width: 160 },
          {
            title: "套餐基础额度",
            width: 140,
            render: (_, quota) => `${formatAmount(quota.entitlement_amount)} ${quota.unit_display_name}`,
          },
          {
            title: "人工调整",
            width: 130,
            render: (_, quota) => (
              <Text type={parseAmount(quota.manual_adjustment_amount) < 0n ? "danger" : undefined}>
                {formatSignedAmount(quota.manual_adjustment_amount)} {quota.unit_display_name}
              </Text>
            ),
          },
          {
            title: "累计已使用",
            width: 130,
            render: (_, quota) => `${formatAmount(quota.used_amount)} ${quota.unit_display_name}`,
          },
          {
            title: "处理中",
            width: 115,
            render: (_, quota) => `${formatAmount(quota.frozen)} ${quota.unit_display_name}`,
          },
          {
            title: "当前可用",
            width: 140,
            render: (_, quota) => (
              <Tag color={parseAmount(quota.available) === 0n ? "red" : "blue"}>
                {formatAmount(quota.available)} {quota.unit_display_name}
              </Tag>
            ),
          },
          {
            title: "底层账户",
            width: 100,
            render: (_, quota) => `${quota.accounts.length} 个`,
          },
          {
            title: "操作",
            fixed: "right",
            width: 120,
            render: (_, quota) => (
              <Button type="primary" size="small" onClick={() => openAdjustment(quota)}>
                调整额度
              </Button>
            ),
          },
        ]}
      />

      <Card title="当前套餐实际执行规则" size="small">
        <Paragraph type="secondary">
          以下内容来自该用户当前订阅的不可变权益快照，是业务执行正在读取的套餐规则。这里只展示真实存在的规则，不制造未接入业务执行的假权限开关。
        </Paragraph>
        <Table<ControlCenterPlanLimit>
          rowKey="key"
          size="small"
          pagination={{ pageSize: 20, hideOnSinglePage: true }}
          dataSource={policyLimits}
          columns={[
            { title: "分类", dataIndex: "category", width: 140 },
            { title: "规则", dataIndex: "name", width: 220 },
            {
              title: "当前值",
              render: (_, limit) => (
                <Text style={{ whiteSpace: "pre-wrap" }}>{formatLimitValue(limit)}</Text>
              ),
            },
            { title: "说明", dataIndex: "description" },
          ]}
        />
        {modelRows.length ? (
          <>
            <Title level={5}>当前模型权限</Title>
            <Table
              rowKey="key"
              size="small"
              pagination={false}
              dataSource={modelRows.sort((a, b) => a.sort_order - b.sort_order)}
              columns={[
                { title: "模型", dataIndex: "model_key" },
                {
                  title: "默认选中",
                  render: (_, item) => (item.selected_by_default ? <Tag color="green">是</Tag> : <Tag>否</Tag>),
                  width: 120,
                },
              ]}
            />
          </>
        ) : null}
      </Card>
    </Space>
  );

  const subscriptions = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card title="当前套餐与订阅" size="small">
        {data.subscription ? (
          <Descriptions bordered column={{ xs: 1, md: 2, xl: 3 }}>
            <Descriptions.Item label="套餐">{data.subscription.plan_name}</Descriptions.Item>
            <Descriptions.Item label="版本">V{data.subscription.plan_version_no}</Descriptions.Item>
            <Descriptions.Item label="状态">
              {subscriptionStatusTag(data.subscription.status)}
            </Descriptions.Item>
            <Descriptions.Item label="来源">
              {sourceLabel(data.subscription.source_type, data.subscription.is_trial)}
            </Descriptions.Item>
            <Descriptions.Item label="生效时间">{formatDate(data.subscription.starts_at)}</Descriptions.Item>
            <Descriptions.Item label="到期时间">{formatDate(data.subscription.ends_at)}</Descriptions.Item>
            <Descriptions.Item label="开通备注" span={3}>
              {data.subscription.opening_note || "无"}
            </Descriptions.Item>
          </Descriptions>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="当前没有生效套餐" />
        )}
      </Card>
      <Card title="套餐历史" size="small">
        <Table<ControlCenterSubscription>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={[...data.subscription_history]}
          columns={[
            { title: "套餐", dataIndex: "plan_name" },
            { title: "版本", render: (_, item) => `V${item.plan_version_no}`, width: 90 },
            {
              title: "来源",
              render: (_, item) => sourceLabel(item.source_type, item.is_trial),
              width: 140,
            },
            { title: "开始", render: (_, item) => formatDate(item.starts_at), width: 180 },
            { title: "结束", render: (_, item) => formatDate(item.ends_at), width: 180 },
            { title: "状态", render: (_, item) => subscriptionStatusTag(item.status), width: 110 },
          ]}
        />
      </Card>
    </Space>
  );

  const usage = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card title={`最近 ${data.usage.window_days} 天业务使用`} size="small">
        {data.usage.items.length ? (
          <Row gutter={[12, 12]}>
            {data.usage.items.map((item) => (
              <Col xs={24} sm={12} lg={8} xl={6} key={item.quota_type}>
                <Card size="small">
                  <Statistic
                    title={item.display_name}
                    value={formatAmount(item.amount)}
                    suffix={item.unit_display_name}
                  />
                </Card>
              </Col>
            ))}
          </Row>
        ) : (
          <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="最近暂无额度消耗" />
        )}
      </Card>
      <Card
        title="最近额度流水"
        extra={<Button href="/admin/quotas">进入客户额度中心</Button>}
        size="small"
      >
        <Table<ControlCenterLedgerEntry>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={[...data.recent_ledger]}
          scroll={{ x: 900 }}
          columns={[
            { title: "时间", render: (_, item) => formatDate(item.created_at), width: 180 },
            { title: "项目", dataIndex: "display_name", width: 150 },
            {
              title: "动作",
              render: (_, item) => ledgerActionLabels[item.action] ?? item.action,
              width: 140,
            },
            {
              title: "变化",
              render: (_, item) => formatSignedAmount(item.available_delta),
              width: 110,
            },
            {
              title: "变化前 → 变化后",
              render: (_, item) => `${formatAmount(item.available_before)} → ${formatAmount(item.available_after)}`,
              width: 220,
            },
            { title: "操作人", dataIndex: "actor_name", width: 130 },
            { title: "原因", dataIndex: "safe_reason" },
          ]}
        />
      </Card>
    </Space>
  );

  const security = (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      <Card title="账号与归属" size="small">
        <Descriptions bordered column={{ xs: 1, md: 2 }}>
          <Descriptions.Item label="账号状态">{statusTag(data.user.account_status)}</Descriptions.Item>
          <Descriptions.Item label="状态版本">{data.user.status_version}</Descriptions.Item>
          <Descriptions.Item label="所属代理 / 管理员">
            {data.user.assignment?.owner_name || "平台直管"}
          </Descriptions.Item>
          <Descriptions.Item label="代理角色">
            {data.user.assignment?.owner_role || "—"}
          </Descriptions.Item>
          <Descriptions.Item label="归属更新时间">
            {formatDate(data.user.assignment?.assigned_at)}
          </Descriptions.Item>
          <Descriptions.Item label="所属租户">
            {data.user.tenant?.display_name || "无"}
          </Descriptions.Item>
        </Descriptions>
      </Card>
      <Card title="最近登录与安全环境" size="small">
        <Table<ControlCenterLoginEvent>
          rowKey="id"
          size="small"
          pagination={false}
          dataSource={[...data.user.login.recent]}
          scroll={{ x: 900 }}
          columns={[
            { title: "时间", render: (_, item) => formatDate(item.created_at), width: 180 },
            {
              title: "结果",
              render: (_, item) =>
                item.success ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag>,
              width: 90,
            },
            { title: "方式", dataIndex: "login_method", width: 110 },
            { title: "IP", render: (_, item) => item.ip_address || "暂无", width: 150 },
            { title: "设备 / 浏览器", dataIndex: "user_agent" },
            { title: "失败原因", render: (_, item) => item.failure_reason || "—", width: 140 },
          ]}
        />
      </Card>
    </Space>
  );

  const audits = (
    <Card
      title="该用户最近敏感操作记录"
      extra={<Button href="/admin/operation-records">进入日志中心</Button>}
      size="small"
    >
      <Table<ControlCenterAuditEntry>
        rowKey="id"
        size="small"
        pagination={false}
        dataSource={[...data.recent_audit]}
        scroll={{ x: 1100 }}
        locale={{ emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无敏感操作" /> }}
        columns={[
          { title: "时间", render: (_, item) => formatDate(item.created_at), width: 180 },
          { title: "操作人", dataIndex: "actor_name_snapshot", width: 140 },
          { title: "身份", dataIndex: "actor_role_snapshot", width: 130 },
          {
            title: "操作",
            render: (_, item) => auditActionLabels[item.action_key] ?? item.action_key,
            width: 160,
          },
          {
            title: "额度变化",
            render: (_, item) => (item.quota_delta === null ? "—" : formatSignedAmount(item.quota_delta)),
            width: 120,
          },
          { title: "操作 IP", render: (_, item) => item.operation_ip || "暂无", width: 150 },
          {
            title: "结果",
            render: (_, item) =>
              item.outcome === "success" ? <Tag color="green">成功</Tag> : <Tag color="red">失败</Tag>,
            width: 90,
          },
          { title: "原因", render: (_, item) => item.safe_reason || item.failure_reason || "—" },
        ]}
      />
    </Card>
  );

  return (
    <Space orientation="vertical" size={16} style={{ width: "100%" }}>
      {error ? <Alert type="error" showIcon title={error} closable onClose={() => setError("")} /> : null}
      {success ? <Alert type="success" showIcon title={success} closable onClose={() => setSuccess("")} /> : null}

      <Card loading={loading}>
        <Row gutter={[20, 16]} align="middle" justify="space-between">
          <Col flex="auto">
            <Space orientation="vertical" size={2}>
              <Space wrap>
                <Title level={3} style={{ margin: 0 }}>
                  {data.user.nickname}
                </Title>
                {statusTag(data.user.account_status)}
                {data.subscription ? <Tag color="blue">{data.subscription.plan_name} V{data.subscription.plan_version_no}</Tag> : <Tag>无套餐</Tag>}
              </Space>
              <Text type="secondary">
                {data.user.phone_masked} · 用户 ID {data.user.id}
              </Text>
              <Text type="secondary">
                {data.user.assignment?.owner_name ? `所属：${data.user.assignment.owner_name}` : "平台直管"}
                {data.subscription ? ` · 套餐到期 ${formatDate(data.subscription.ends_at)}` : ""}
                {data.user.login.last_success_at ? ` · 最近登录 ${formatDate(data.user.login.last_success_at)}` : ""}
              </Text>
            </Space>
          </Col>
          <Col>
            <Space wrap>
              <Button type="primary" onClick={() => setActiveTab("entitlements")}>
                调整额度 / 权益
              </Button>
              <Button onClick={() => setActiveTab("subscriptions")}>套餐与订阅</Button>
              <Button onClick={() => setActiveTab("security")}>安全与归属</Button>
              <Button onClick={() => setActiveTab("audit")}>操作记录</Button>
            </Space>
          </Col>
        </Row>
      </Card>

      <Card>
        <Tabs
          activeKey={activeTab}
          onChange={setActiveTab}
          items={[
            { key: "overview", label: "用户概览", children: overview },
            { key: "entitlements", label: "权益与额度", children: entitlements },
            { key: "subscriptions", label: "套餐与订阅", children: subscriptions },
            { key: "usage", label: "业务使用", children: usage },
            { key: "security", label: "安全与归属", children: security },
            { key: "audit", label: "操作记录", children: audits },
          ]}
        />
      </Card>

      <Modal
        width={680}
        open={Boolean(selectedQuota && selectedAccount)}
        title={selectedQuota ? `调整额度 · ${selectedQuota.display_name}` : "调整额度"}
        okText="确认调整"
        cancelText="取消"
        confirmLoading={submitting}
        onOk={() => void submitAdjustment()}
        onCancel={closeAdjustment}
      >
        {selectedQuota && selectedAccount ? (
          <Space orientation="vertical" size={14} style={{ width: "100%" }}>
            <Alert
              type="info"
              showIcon
              title={`该项目合计可用 ${formatAmount(selectedQuota.available)} ${selectedQuota.unit_display_name}`}
              description={`当前选中账户可用 ${formatAmount(selectedAccount.available)} ${selectedQuota.unit_display_name}。所有修改都会写入额度流水和审计日志。`}
            />
            <Form form={form} layout="vertical">
              {selectedQuota.accounts.filter((account) => account.adjustable).length > 1 ? (
                <Form.Item label="调整账户">
                  <Select
                    value={selectedAccountId}
                    onChange={setSelectedAccountId}
                    options={selectedQuota.accounts
                      .filter((account) => account.adjustable)
                      .map((account, index) => ({
                        value: account.id,
                        label: accountLabel(account, index),
                      }))}
                  />
                </Form.Item>
              ) : null}
              <Form.Item label="调整方式">
                <Select
                  value={adjustmentMode}
                  onChange={setAdjustmentMode}
                  options={[
                    { value: "increase", label: "增加额度" },
                    { value: "deduct", label: "扣减额度" },
                    { value: "target", label: "设置目标余额" },
                  ]}
                />
              </Form.Item>
              <Form.Item
                name="amount"
                label={adjustmentMode === "target" ? "目标余额" : "调整数量"}
                rules={[
                  { required: true, message: adjustmentMode === "target" ? "请输入目标余额" : "请输入调整数量" },
                  { pattern: /^\d+$/, message: "必须输入非负整数" },
                ]}
              >
                <Input
                  inputMode="numeric"
                  maxLength={19}
                  placeholder={adjustmentMode === "target" ? "例如：10000" : "例如：5000"}
                  addonAfter={selectedQuota.unit_display_name}
                />
              </Form.Item>
              <Form.Item
                name="reason"
                label="操作原因"
                rules={[{ required: true, message: "请填写操作原因" }]}
              >
                <Input.TextArea
                  rows={3}
                  maxLength={500}
                  showCount
                  placeholder="例如：客户增购额度、合同定制权益、误操作修正等"
                />
              </Form.Item>
            </Form>
            <Text type="secondary">
              “设置目标余额”不会直接覆盖数据库余额，而是自动换算成一笔增加或扣减流水，确保历史可追溯。
            </Text>
          </Space>
        ) : null}
      </Modal>
    </Space>
  );
}
