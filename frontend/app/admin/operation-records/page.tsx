"use client";

import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Descriptions,
  Empty,
  Input,
  Modal,
  Pagination,
  Select,
  Space,
  Spin,
  Table,
  Tabs,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { AdminPageHeader } from "@/components/admin/admin-page-header";
import {
  getSensitiveAuditLog,
  getSensitiveAuditLogs,
  type AuditInteger,
  type SensitiveAuditFilters,
  type SensitiveAuditLog,
} from "@/lib/admin-audit-client";
import { userMessage, type PageData } from "@/lib/auth-client";
import { getAuditEvents, type AuditEvent } from "@/lib/risk-client";

const ACTION_LABELS: Record<string, string> = {
  "quota.grant": "增加额度",
  "quota.compensate": "补偿额度",
  "quota.manual_deduct": "减少额度",
  "admin.disable": "停用管理员",
  "admin.lock": "锁定管理员",
  "admin.role.change": "修改管理员角色",
  "admin.force_logout": "强制管理员退出",
  "role.permissions.replace": "修改角色权限",
  "role.disable": "停用角色",
  "role.security.update": "修改角色安全策略",
  "role.ip_allowlist.update": "修改角色 IP 白名单",
  "superuser.ip_allowlist.update": "修改超级管理员 IP 白名单",
  "customer.assignment.change": "修改用户归属",
  "user.freeze": "禁用用户",
  "subscription.open": "开通套餐",
  "subscription.grant_trial": "发放试用套餐",
  "subscription.terminate": "终止套餐",
  "subscription.change": "调整套餐",
  "subscription.change.cancel": "取消套餐调整",
};

const QUOTA_LABELS: Record<string, string> = {
  detection_points: "检测点数",
  article_credits: "文章额度",
  image_credits: "图片额度",
  storage_bytes: "存储空间",
  assistant_messages: "AI 助手消息",
};

const friendlyAction = (event: AuditEvent) => {
  if (event.action_key.includes("admin")) return "管理员管理";
  if (event.action_key.includes("user")) return "用户管理";
  if (event.action_key.includes("quota")) return "额度调整";
  if (event.action_key.includes("plan") || event.action_key.includes("subscription"))
    return "套餐管理";
  if (event.action_key.includes("model") || event.action_key.includes("credential"))
    return "模型与接口";
  return "平台操作";
};

const friendlyTarget = (event: AuditEvent) => {
  const target = event.target_type;
  if (target.includes("admin")) return "管理员";
  if (target.includes("user") || target.includes("customer")) return "用户";
  if (target.includes("quota")) return "用户额度";
  if (target.includes("plan") || target.includes("subscription")) return "套餐";
  if (target.includes("model") || target.includes("credential")) return "模型接口";
  return "平台数据";
};

const operationSucceeded = (outcome: string) =>
  ["success", "succeeded", "executed", "completed", "updated"].includes(outcome);

const parseAuditInteger = (value: AuditInteger | undefined): bigint | null => {
  if (value === null || value === undefined || value === "") return null;
  try {
    return BigInt(value);
  } catch {
    return null;
  }
};

const formatNumber = (value: AuditInteger | undefined) => {
  const parsed = parseAuditInteger(value);
  return parsed === null ? "—" : parsed.toLocaleString("zh-CN");
};

const formatDelta = (value: AuditInteger | undefined) => {
  const parsed = parseAuditInteger(value);
  if (parsed === null) return "—";
  const absolute = parsed < 0n ? -parsed : parsed;
  return `${parsed >= 0n ? "+" : "-"}${absolute.toLocaleString("zh-CN")}`;
};

const deviceSummary = (userAgent = "") => {
  if (!userAgent) return "—";
  const os = /Windows/i.test(userAgent)
    ? "Windows"
    : /Mac OS|Macintosh/i.test(userAgent)
      ? "macOS"
      : /Android/i.test(userAgent)
        ? "Android"
        : /iPhone|iPad/i.test(userAgent)
          ? "iOS"
          : /Linux/i.test(userAgent)
            ? "Linux"
            : "未知系统";
  const browser = /Edg\//i.test(userAgent)
    ? "Edge"
    : /Chrome\//i.test(userAgent)
      ? "Chrome"
      : /Firefox\//i.test(userAgent)
        ? "Firefox"
        : /Safari\//i.test(userAgent)
          ? "Safari"
          : "未知浏览器";
  return `${os} / ${browser}`;
};

const asRecord = (value: unknown): Record<string, unknown> | null =>
  typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;

const hasEntries = (value: Record<string, unknown> | null) =>
  value !== null && Object.keys(value).length > 0;

type AuditDraft = {
  q: string;
  actionKey: string;
  outcome: "" | "success" | "failure";
  range: "7" | "30" | "90" | "365" | "custom";
  dateFrom: string;
  dateTo: string;
};

const initialAuditDraft: AuditDraft = {
  q: "",
  actionKey: "",
  outcome: "",
  range: "7",
  dateFrom: "",
  dateTo: "",
};

function toAuditFilters(draft: AuditDraft): SensitiveAuditFilters {
  if (draft.range === "custom") {
    return {
      q: draft.q,
      actionKey: draft.actionKey,
      outcome: draft.outcome,
      dateFrom: draft.dateFrom,
      dateTo: draft.dateTo,
    };
  }
  return {
    q: draft.q,
    actionKey: draft.actionKey,
    outcome: draft.outcome,
    days: Number(draft.range),
  };
}

export default function AdminOperationRecordsPage() {
  const context = useAdminCapabilities();
  const isSuperAdmin = context?.commercial_identity === "SUPER_ADMIN";
  const [activeTab, setActiveTab] = useState("operations");

  const [operationData, setOperationData] = useState<PageData<AuditEvent> | null>(null);
  const [operationPage, setOperationPage] = useState(1);
  const [operationKeyword, setOperationKeyword] = useState("");
  const [operationLoading, setOperationLoading] = useState(true);

  const [auditData, setAuditData] = useState<PageData<SensitiveAuditLog> | null>(null);
  const [auditPage, setAuditPage] = useState(1);
  const [auditDraft, setAuditDraft] = useState<AuditDraft>(initialAuditDraft);
  const [auditFilters, setAuditFilters] = useState<SensitiveAuditFilters>({ days: 7 });
  const [auditLoading, setAuditLoading] = useState(false);
  const [selected, setSelected] = useState<SensitiveAuditLog | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState("");

  const loadOperations = useCallback(async () => {
    setOperationLoading(true);
    setError("");
    try {
      setOperationData(await getAuditEvents(operationPage));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setOperationLoading(false);
    }
  }, [operationPage]);

  const loadAudit = useCallback(async () => {
    if (!isSuperAdmin || activeTab !== "audit") return;
    setAuditLoading(true);
    setError("");
    try {
      setAuditData(await getSensitiveAuditLogs(auditPage, auditFilters));
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setAuditLoading(false);
    }
  }, [activeTab, auditFilters, auditPage, isSuperAdmin]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadOperations();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadOperations]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadAudit();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [loadAudit]);

  const visibleOperations = useMemo(() => {
    const records = operationData?.results ?? [];
    const query = operationKeyword.trim().toLocaleLowerCase("zh-CN");
    if (!query) return records;
    return records.filter((record) =>
      `${friendlyAction(record)} ${friendlyTarget(record)} ${record.action_key} ${record.target_type}`
        .toLocaleLowerCase("zh-CN")
        .includes(query),
    );
  }, [operationData, operationKeyword]);

  const auditActionOptions = useMemo(
    () =>
      Object.entries(ACTION_LABELS).map(([value, label]) => ({
        value,
        label,
      })),
    [],
  );

  const openDetail = async (record: SensitiveAuditLog) => {
    setSelected(record);
    setDetailLoading(true);
    setError("");
    try {
      setSelected(await getSensitiveAuditLog(record.id));
    } catch (reason) {
      setSelected(null);
      setError(userMessage(reason));
    } finally {
      setDetailLoading(false);
    }
  };

  const applyAuditFilters = () => {
    if (auditDraft.range === "custom") {
      if (!auditDraft.dateFrom || !auditDraft.dateTo) {
        setError("自定义时间需要同时选择开始日期和结束日期。");
        return;
      }
      if (auditDraft.dateFrom > auditDraft.dateTo) {
        setError("结束日期不能早于开始日期。");
        return;
      }
    }
    setError("");
    setAuditPage(1);
    setAuditFilters(toAuditFilters(auditDraft));
  };

  const resetAuditFilters = () => {
    setError("");
    setAuditDraft(initialAuditDraft);
    setAuditPage(1);
    setAuditFilters({ days: 7 });
  };

  const refresh = () => {
    if (activeTab === "audit") void loadAudit();
    else void loadOperations();
  };

  const operationPanel = (
    <>
      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索操作类型或操作对象"
          value={operationKeyword}
          onChange={(event) => setOperationKeyword(event.target.value)}
          style={{ maxWidth: 360 }}
        />
      </Card>
      <Table<AuditEvent>
        rowKey="id"
        loading={operationLoading}
        dataSource={visibleOperations}
        pagination={false}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无操作记录" />,
        }}
        columns={[
          {
            title: "时间",
            dataIndex: "created_at",
            width: 190,
            render: (value: string) => new Date(value).toLocaleString("zh-CN"),
          },
          { title: "操作人", render: (_, record) => (record.actor_id ? "平台管理员" : "系统") },
          { title: "操作类型", render: (_, record) => friendlyAction(record) },
          { title: "操作对象", render: (_, record) => friendlyTarget(record) },
          {
            title: "结果",
            render: (_, record) => (
              <Tag color={operationSucceeded(record.outcome) ? "green" : "orange"}>
                {operationSucceeded(record.outcome) ? "成功" : "未完成"}
              </Tag>
            ),
          },
          { title: "请求 ID", dataIndex: "request_id", ellipsis: true },
        ]}
      />
      <Pagination
        current={operationData?.pagination.page ?? operationPage}
        pageSize={operationData?.pagination.page_size ?? 20}
        total={operationData?.pagination.count ?? 0}
        showSizeChanger={false}
        onChange={setOperationPage}
        style={{ marginTop: 18, textAlign: "right" }}
      />
    </>
  );

  const auditPanel = (
    <>
      <Alert
        type="info"
        showIcon
        title="敏感审计证据保留 365 天"
        description="记录额度、套餐、权限和关键账号操作。日志不可人工修改或单条删除；页面默认查询最近 7 天。"
        style={{ marginBottom: 18 }}
      />
      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Space wrap align="start">
          <Input
            allowClear
            prefix={<SearchOutlined />}
            placeholder="代理 / 用户 / IP / 流水号"
            value={auditDraft.q}
            onChange={(event) =>
              setAuditDraft((current) => ({ ...current, q: event.target.value }))
            }
            onPressEnter={applyAuditFilters}
            style={{ width: 300 }}
          />
          <Select
            allowClear
            showSearch
            optionFilterProp="label"
            placeholder="操作类型"
            value={auditDraft.actionKey || undefined}
            onChange={(value) =>
              setAuditDraft((current) => ({ ...current, actionKey: value ?? "" }))
            }
            options={auditActionOptions}
            style={{ width: 210 }}
          />
          <Select
            placeholder="状态"
            value={auditDraft.outcome || undefined}
            allowClear
            onChange={(value) =>
              setAuditDraft((current) => ({
                ...current,
                outcome: (value ?? "") as AuditDraft["outcome"],
              }))
            }
            options={[
              { value: "success", label: "成功" },
              { value: "failure", label: "失败" },
            ]}
            style={{ width: 130 }}
          />
          <Select
            value={auditDraft.range}
            onChange={(value) =>
              setAuditDraft((current) => ({ ...current, range: value as AuditDraft["range"] }))
            }
            options={[
              { value: "7", label: "最近 7 天" },
              { value: "30", label: "最近 30 天" },
              { value: "90", label: "最近 90 天" },
              { value: "365", label: "最近 365 天" },
              { value: "custom", label: "自定义时间" },
            ]}
            style={{ width: 150 }}
          />
          {auditDraft.range === "custom" ? (
            <>
              <Input
                type="date"
                aria-label="开始日期"
                value={auditDraft.dateFrom}
                onChange={(event) =>
                  setAuditDraft((current) => ({ ...current, dateFrom: event.target.value }))
                }
                style={{ width: 160 }}
              />
              <Input
                type="date"
                aria-label="结束日期"
                value={auditDraft.dateTo}
                onChange={(event) =>
                  setAuditDraft((current) => ({ ...current, dateTo: event.target.value }))
                }
                style={{ width: 160 }}
              />
            </>
          ) : null}
          <Button type="primary" onClick={applyAuditFilters}>
            查询
          </Button>
          <Button onClick={resetAuditFilters}>重置</Button>
        </Space>
      </Card>
      <Table<SensitiveAuditLog>
        rowKey="id"
        loading={auditLoading}
        dataSource={auditData?.results ?? []}
        pagination={false}
        scroll={{ x: 1120 }}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无审计日志" />,
        }}
        columns={[
          {
            title: "时间",
            dataIndex: "created_at",
            width: 180,
            render: (value: string) => new Date(value).toLocaleString("zh-CN"),
          },
          {
            title: "操作人",
            width: 170,
            render: (_, record) => (
              <Space direction="vertical" size={0}>
                <Typography.Text>{record.actor_name_snapshot || "系统"}</Typography.Text>
                <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                  {record.actor_role_snapshot || "—"}
                </Typography.Text>
              </Space>
            ),
          },
          {
            title: "目标用户",
            width: 190,
            render: (_, record) => (
              <Space direction="vertical" size={0}>
                <Typography.Text>{record.target_name_snapshot || "—"}</Typography.Text>
                {record.target_owner_name_snapshot ? (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    代理：{record.target_owner_name_snapshot}
                  </Typography.Text>
                ) : record.target_tenant_name_snapshot ? (
                  <Typography.Text type="secondary" style={{ fontSize: 12 }}>
                    租户：{record.target_tenant_name_snapshot}
                  </Typography.Text>
                ) : null}
              </Space>
            ),
          },
          {
            title: "操作",
            dataIndex: "action_key",
            width: 170,
            render: (value: string) => ACTION_LABELS[value] ?? value,
          },
          {
            title: "额度变化",
            width: 130,
            align: "right",
            render: (_, record) => {
              const value = record.quota_delta ?? record.quota_requested_delta;
              if (value === null || value === undefined) return "—";
              return (
                <Typography.Text strong={record.outcome === "success"}>
                  {formatDelta(value)}
                  {record.outcome === "failure" ? "（请求）" : ""}
                </Typography.Text>
              );
            },
          },
          {
            title: "操作 IP",
            dataIndex: "operation_ip",
            width: 150,
            render: (value: string | null) => value || "—",
          },
          {
            title: "状态",
            width: 90,
            render: (_, record) => (
              <Tag color={record.outcome === "success" ? "green" : "red"}>
                {record.outcome === "success" ? "成功" : "失败"}
              </Tag>
            ),
          },
          {
            title: "详情",
            fixed: "right",
            width: 80,
            render: (_, record) => (
              <Button type="link" onClick={() => void openDetail(record)}>
                查看
              </Button>
            ),
          },
        ]}
      />
      <Pagination
        current={auditData?.pagination.page ?? auditPage}
        pageSize={auditData?.pagination.page_size ?? 20}
        total={auditData?.pagination.count ?? 0}
        showSizeChanger={false}
        onChange={setAuditPage}
        style={{ marginTop: 18, textAlign: "right" }}
      />
    </>
  );

  const safeBefore = asRecord(selected?.details?.safe_before);
  const safeAfter = asRecord(selected?.details?.safe_after);

  return (
    <div className="admin-page">
      <AdminPageHeader
        title="日志中心"
        description="集中查看普通后台操作与敏感审计证据，用于日常追踪、额度核查和责任追溯。"
        actions={
          <Button
            icon={<ReloadOutlined />}
            onClick={refresh}
            loading={activeTab === "audit" ? auditLoading : operationLoading}
          >
            刷新
          </Button>
        }
      />
      {error ? (
        <Alert
          type="error"
          showIcon
          title="日志处理失败"
          description={error}
          style={{ marginBottom: 18 }}
        />
      ) : null}
      <Tabs
        activeKey={activeTab}
        onChange={setActiveTab}
        items={[
          { key: "operations", label: "操作记录", children: operationPanel },
          ...(isSuperAdmin ? [{ key: "audit", label: "审计日志", children: auditPanel }] : []),
        ]}
      />

      <Modal
        title="审计日志详情"
        open={Boolean(selected)}
        onCancel={() => setSelected(null)}
        footer={null}
        width={920}
      >
        <Spin spinning={detailLoading}>
          {selected ? (
            <Space direction="vertical" size="large" style={{ width: "100%" }}>
              <Descriptions bordered column={2} size="small">
                <Descriptions.Item label="审计 ID" span={2}>
                  <Typography.Text copyable>{selected.id}</Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="操作时间">
                  {new Date(selected.created_at).toLocaleString("zh-CN")}
                </Descriptions.Item>
                <Descriptions.Item label="执行结果">
                  <Tag color={selected.outcome === "success" ? "green" : "red"}>
                    {selected.outcome === "success" ? "成功" : "失败"}
                  </Tag>
                </Descriptions.Item>
                <Descriptions.Item label="操作类型">
                  {ACTION_LABELS[selected.action_key] ?? selected.action_key}
                </Descriptions.Item>
                <Descriptions.Item label="操作渠道">
                  {selected.channel === "admin_console" ? "后台管理" : selected.channel}
                </Descriptions.Item>
              </Descriptions>

              <Descriptions title="操作人" bordered column={2} size="small">
                <Descriptions.Item label="姓名">
                  {selected.actor_name_snapshot || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="身份">
                  {selected.actor_role_snapshot || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="操作人 ID">
                  {selected.actor_user_id_snapshot || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="所属租户">
                  {selected.actor_tenant_name_snapshot || "—"}
                </Descriptions.Item>
              </Descriptions>

              <Descriptions title="目标用户" bordered column={2} size="small">
                <Descriptions.Item label="用户名 / 姓名">
                  {selected.target_name_snapshot || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="用户 ID">
                  {selected.target_user_id_snapshot || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="所属代理">
                  {selected.target_owner_name_snapshot || "独立用户 / 未分配"}
                </Descriptions.Item>
                <Descriptions.Item label="代理账号 ID">
                  {selected.target_owner_user_id_snapshot || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="所属租户" span={2}>
                  {selected.target_tenant_name_snapshot || "—"}
                </Descriptions.Item>
              </Descriptions>

              <Descriptions title="额度证据" bordered column={2} size="small">
                <Descriptions.Item label="额度类型">
                  {(QUOTA_LABELS[selected.quota_type] ?? selected.quota_type) || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="流水 ID">
                  {selected.ledger_entry_id || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="变更前">
                  {formatNumber(selected.quota_before)}
                </Descriptions.Item>
                <Descriptions.Item label="请求变化">
                  {formatDelta(selected.quota_requested_delta)}
                </Descriptions.Item>
                <Descriptions.Item label="实际变化">
                  {formatDelta(selected.quota_delta)}
                </Descriptions.Item>
                <Descriptions.Item label="变更后">
                  {formatNumber(selected.quota_after)}
                </Descriptions.Item>
              </Descriptions>

              <Descriptions title="操作环境" bordered column={2} size="small">
                <Descriptions.Item label="操作 IP">
                  {selected.operation_ip || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="登录 IP">
                  {selected.login_ip_snapshot || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="设备 / 浏览器" span={2}>
                  {deviceSummary(selected.user_agent)}
                </Descriptions.Item>
                <Descriptions.Item label="User-Agent" span={2}>
                  <Typography.Text copyable={Boolean(selected.user_agent)}>
                    {selected.user_agent || "—"}
                  </Typography.Text>
                </Descriptions.Item>
              </Descriptions>

              <Descriptions title="追踪与原因" bordered column={2} size="small">
                <Descriptions.Item label="Request ID" span={2}>
                  <Typography.Text copyable>{selected.request_id}</Typography.Text>
                </Descriptions.Item>
                <Descriptions.Item label="操作原因" span={2}>
                  {selected.safe_reason || "—"}
                </Descriptions.Item>
                <Descriptions.Item label="失败原因" span={2}>
                  {selected.failure_reason || "—"}
                </Descriptions.Item>
              </Descriptions>

              {hasEntries(safeBefore) || hasEntries(safeAfter) ? (
                <Descriptions title="变更安全摘要" bordered column={1} size="small">
                  {hasEntries(safeBefore) ? (
                    <Descriptions.Item label="执行前">
                      <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(safeBefore, null, 2)}
                      </Typography.Paragraph>
                    </Descriptions.Item>
                  ) : null}
                  {hasEntries(safeAfter) ? (
                    <Descriptions.Item label="执行后">
                      <Typography.Paragraph style={{ marginBottom: 0, whiteSpace: "pre-wrap" }}>
                        {JSON.stringify(safeAfter, null, 2)}
                      </Typography.Paragraph>
                    </Descriptions.Item>
                  ) : null}
                </Descriptions>
              ) : null}
            </Space>
          ) : null}
        </Spin>
      </Modal>
    </div>
  );
}
