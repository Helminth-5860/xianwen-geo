"use client";

import { ReloadOutlined, SearchOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Input, Table, Tag } from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { userMessage } from "@/lib/auth-client";
import { getAuditEvents, type AuditEvent } from "@/lib/risk-client";

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
  ["success", "executed", "completed"].includes(outcome);

export default function AdminOperationRecordsPage() {
  const [records, setRecords] = useState<AuditEvent[]>([]);
  const [keyword, setKeyword] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const page = await getAuditEvents(1);
      setRecords(page.results);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const visibleRecords = useMemo(() => {
    const query = keyword.trim();
    if (!query) return records;
    return records.filter((record) =>
      `${friendlyAction(record)} ${friendlyTarget(record)}`.includes(query),
    );
  }, [keyword, records]);

  return (
    <div className="admin-page">
      <AdminPageHeader
        title="操作记录"
        description="查看重要的平台管理动作和执行结果，便于日常追踪和问题排查。"
        actions={
          <Button icon={<ReloadOutlined />} onClick={() => void load()} loading={loading}>
            刷新
          </Button>
        }
      />
      {error ? <Alert type="error" showIcon title="操作记录加载失败" description={error} /> : null}
      <Card className="admin-surface" style={{ marginBottom: 18 }}>
        <Input
          allowClear
          prefix={<SearchOutlined />}
          placeholder="搜索操作类型或操作对象"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          style={{ maxWidth: 360 }}
        />
      </Card>
      <Table
        rowKey="id"
        loading={loading}
        dataSource={visibleRecords}
        pagination={{ pageSize: 15, hideOnSinglePage: true }}
        locale={{
          emptyText: <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无操作记录" />,
        }}
        columns={[
          {
            title: "时间",
            dataIndex: "created_at",
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
          {
            title: "备注",
            render: (_, record) =>
              operationSucceeded(record.outcome) ? "操作已记录" : "请查看相关业务状态",
          },
        ]}
      />
    </div>
  );
}
