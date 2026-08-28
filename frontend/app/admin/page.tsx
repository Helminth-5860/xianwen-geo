"use client";

import {
  ApiOutlined,
  BarChartOutlined,
  CreditCardOutlined,
  ExclamationCircleOutlined,
  FileTextOutlined,
  RadarChartOutlined,
  TeamOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Card, Empty, Skeleton, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { getAdmins } from "@/lib/admin-rbac-client";
import { getAIModels, type AIModelRuntimeConfig } from "@/lib/ai-model-config-client";
import { getAdminUsers } from "@/lib/auth-client";
import {
  getOperationsTasks,
  getReleaseReadiness,
  type OperationsTask,
  type ReleaseReadiness,
} from "@/lib/operations-client";
import { getAuditEvents, type AuditEvent } from "@/lib/risk-client";

type Overview = Readonly<{
  adminCount: number | null;
  userCount: number | null;
  enabledModelCount: number | null;
  failedTaskCount: number | null;
  models: AIModelRuntimeConfig[];
  tasks: OperationsTask[];
  records: AuditEvent[];
  readiness: ReleaseReadiness | null;
}>;

const initialOverview: Overview = {
  adminCount: null,
  userCount: null,
  enabledModelCount: null,
  failedTaskCount: null,
  models: [],
  tasks: [],
  records: [],
  readiness: null,
};

const failedTask = (task: OperationsTask) =>
  ["failed", "error", "dead", "cancelled"].includes(task.status.toLowerCase());

const friendlyAction = (event: AuditEvent) => {
  const key = event.action_key;
  if (key.includes("admin")) return "管理员信息调整";
  if (key.includes("quota")) return "用户额度调整";
  if (key.includes("plan") || key.includes("subscription")) return "套餐信息调整";
  if (key.includes("model") || key.includes("credential")) return "模型接口调整";
  if (key.includes("user")) return "用户信息调整";
  return "平台运营操作";
};

function MetricCard({
  label,
  value,
  note,
  icon,
}: {
  label: string;
  value: string | number | null;
  note: string;
  icon: ReactNode;
}) {
  return (
    <div className="admin-metric-card">
      <div className="admin-metric-card__top">
        <span>{label}</span>
        <span className="admin-metric-card__icon">{icon}</span>
      </div>
      <strong>{value ?? "—"}</strong>
      <small>{note}</small>
    </div>
  );
}

export default function AdminDashboardPage() {
  const [overview, setOverview] = useState<Overview>(initialOverview);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    const [admins, users, models, tasks, records, readiness] = await Promise.allSettled([
      getAdmins(),
      getAdminUsers({ page: 1 }),
      getAIModels(),
      getOperationsTasks(),
      getAuditEvents(1),
      getReleaseReadiness(),
    ]);
    const modelRows = models.status === "fulfilled" ? models.value : [];
    const taskRows = tasks.status === "fulfilled" ? tasks.value.items : [];
    setOverview({
      adminCount: admins.status === "fulfilled" ? admins.value.pagination.count : null,
      userCount: users.status === "fulfilled" ? users.value.pagination.count : null,
      enabledModelCount:
        models.status === "fulfilled"
          ? modelRows.filter((model) => model.enabled && !model.paused).length
          : null,
      failedTaskCount: tasks.status === "fulfilled" ? taskRows.filter(failedTask).length : null,
      models: modelRows,
      tasks: taskRows.filter(failedTask).slice(0, 5),
      records: records.status === "fulfilled" ? records.value.results.slice(0, 6) : [],
      readiness: readiness.status === "fulfilled" ? readiness.value : null,
    });
    setLoading(false);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const ready = overview.readiness?.status === "READY";
  const runningModels = overview.models
    .filter((model) => model.enabled && !model.paused)
    .slice(0, 4);

  return (
    <div className="admin-page">
      <AdminPageHeader
        title="平台总览"
        description="集中查看用户增长、模型运行、任务异常和平台健康状态，快速处理日常运营事项。"
        actions={
          <Button onClick={() => void load()} loading={loading}>
            刷新数据
          </Button>
        }
      />

      {loading ? (
        <Card className="admin-surface">
          <Skeleton active paragraph={{ rows: 6 }} />
        </Card>
      ) : (
        <>
          <section className="admin-metric-grid" aria-label="平台核心数据">
            <MetricCard
              label="管理员数量"
              value={overview.adminCount}
              note="当前平台管理账号"
              icon={<TeamOutlined />}
            />
            <MetricCard
              label="用户数量"
              value={overview.userCount}
              note="已进入平台的企业用户"
              icon={<UserOutlined />}
            />
            <MetricCard
              label="付费用户数量"
              value={null}
              note="统计接口待接入"
              icon={<CreditCardOutlined />}
            />
            <MetricCard
              label="今日检测次数"
              value={null}
              note="当日统计接口待接入"
              icon={<RadarChartOutlined />}
            />
            <MetricCard
              label="今日报告生成数"
              value={null}
              note="当日统计接口待接入"
              icon={<FileTextOutlined />}
            />
            <MetricCard
              label="今日额度消耗"
              value={null}
              note="当日统计接口待接入"
              icon={<BarChartOutlined />}
            />
            <MetricCard
              label="当前启用模型"
              value={overview.enabledModelCount}
              note="已启用且未暂停"
              icon={<ApiOutlined />}
            />
            <MetricCard
              label="异常任务"
              value={overview.failedTaskCount}
              note="当前任务列表中的异常项"
              icon={<ExclamationCircleOutlined />}
            />
          </section>

          <section className="admin-dashboard-grid">
            <Card className="admin-surface">
              <div className="admin-section-title">
                <Typography.Title level={4}>最近操作记录</Typography.Title>
                <Link href="/admin/operation-records">查看全部</Link>
              </div>
              {overview.records.length ? (
                overview.records.map((record) => (
                  <div className="admin-list-row" key={record.id}>
                    <div className="admin-list-row__copy">
                      <strong>{friendlyAction(record)}</strong>
                      <small>{new Date(record.created_at).toLocaleString("zh-CN")}</small>
                    </div>
                    <Tag color={record.outcome === "success" ? "green" : "orange"}>
                      {record.outcome === "success" ? "已完成" : "未完成"}
                    </Tag>
                  </div>
                ))
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无操作记录" />
              )}
            </Card>

            <Card className="admin-surface">
              <div className="admin-section-title">
                <Typography.Title level={4}>系统状态概览</Typography.Title>
                <Link href="/admin/system-status">查看详情</Link>
              </div>
              <div className="admin-list-row">
                <div className="admin-list-row__copy">
                  <strong>核心服务</strong>
                  <small>数据库、缓存、任务队列与外部能力</small>
                </div>
                <Tag color={ready ? "green" : overview.readiness ? "orange" : "default"}>
                  {ready ? "运行正常" : overview.readiness ? "部分需配置" : "暂未获取"}
                </Tag>
              </div>
              <div className="admin-section-title" style={{ marginTop: 24 }}>
                <Typography.Title level={4}>模型状态摘要</Typography.Title>
                <Link href="/admin/models">管理模型</Link>
              </div>
              {runningModels.length ? (
                runningModels.map((model) => (
                  <div className="admin-list-row" key={model.model_id}>
                    <div className="admin-list-row__copy">
                      <strong>{model.display_name}</strong>
                      <small>接口已启用</small>
                    </div>
                    <Tag color="green">正常</Tag>
                  </div>
                ))
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无启用模型" />
              )}
            </Card>
          </section>

          <section className="admin-dashboard-grid admin-dashboard-grid--equal">
            <Card className="admin-surface">
              <div className="admin-section-title">
                <Typography.Title level={4}>最近异常任务</Typography.Title>
                <Link href="/admin/business-data">查看业务数据</Link>
              </div>
              {overview.tasks.length ? (
                overview.tasks.map((task) => (
                  <div className="admin-list-row" key={task.id}>
                    <div className="admin-list-row__copy">
                      <strong>业务任务执行异常</strong>
                      <small>{new Date(task.created_at).toLocaleString("zh-CN")}</small>
                    </div>
                    <Tag color="red">需要关注</Tag>
                  </div>
                ))
              ) : (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无异常任务" />
              )}
            </Card>

            <Card className="admin-surface">
              <div className="admin-section-title">
                <Typography.Title level={4}>快捷入口</Typography.Title>
              </div>
              <div className="admin-quick-grid">
                <Link className="admin-quick-link" href="/admin/admins">
                  <span>
                    <TeamOutlined />
                  </span>
                  <div>
                    <strong>创建管理员</strong>
                    <small>配置新的企业管理账号</small>
                  </div>
                </Link>
                <Link className="admin-quick-link" href="/admin/quotas">
                  <span>
                    <BarChartOutlined />
                  </span>
                  <div>
                    <strong>调整额度</strong>
                    <small>查看并调整用户可用额度</small>
                  </div>
                </Link>
                <Link className="admin-quick-link" href="/admin/models">
                  <span>
                    <ApiOutlined />
                  </span>
                  <div>
                    <strong>配置模型</strong>
                    <small>检查接口与模型运行状态</small>
                  </div>
                </Link>
              </div>
            </Card>
          </section>
        </>
      )}
    </div>
  );
}
