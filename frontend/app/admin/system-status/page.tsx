"use client";

import { CheckCircleOutlined, ExclamationCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Empty, Skeleton, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import {
  getOperationsTasks,
  getReleaseReadiness,
  type OperationsTask,
  type ReleaseCheck,
} from "@/lib/operations-client";

type ServiceState = Readonly<{ label: string; description: string; ready: boolean | null }>;

const serviceDefinitions = [
  { key: "frontend", label: "前端服务", description: "管理后台与用户工作台" },
  { key: "backend", label: "后端服务", description: "业务接口与权限服务" },
  { key: "database", label: "数据库", description: "平台业务数据存储" },
  { key: "redis", label: "Redis", description: "登录状态与任务缓存" },
  { key: "workers", label: "队列与 Worker", description: "后台任务处理能力" },
  { key: "capability_runtime", label: "模型调用", description: "文本与图片模型运行能力" },
] as const;

const checkByKey = (checks: ReleaseCheck[], key: string) => checks.find((item) => item.key === key);
const isFailedTask = (task: OperationsTask) =>
  ["failed", "error", "dead", "cancelled"].includes(task.status.toLowerCase());

export default function AdminSystemStatusPage() {
  const [services, setServices] = useState<ServiceState[]>([]);
  const [failedTasks, setFailedTasks] = useState<OperationsTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    const [frontend, readiness, tasks] = await Promise.allSettled([
      fetch("/api/health", { headers: { Accept: "application/json" } }),
      getReleaseReadiness(),
      getOperationsTasks(),
    ]);
    const checks = readiness.status === "fulfilled" ? readiness.value.checks : [];
    const frontendReady = frontend.status === "fulfilled" && frontend.value.ok;
    setServices(
      serviceDefinitions.map((definition) => {
        if (definition.key === "frontend") return { ...definition, ready: frontendReady };
        if (definition.key === "backend") {
          return { ...definition, ready: readiness.status === "fulfilled" };
        }
        const check = checkByKey(checks, definition.key);
        return { ...definition, ready: check ? check.status === "READY" : null };
      }),
    );
    setFailedTasks(
      tasks.status === "fulfilled" ? tasks.value.items.filter(isFailedTask).slice(0, 10) : [],
    );
    if (readiness.status === "rejected") setError("系统状态暂时无法完整获取，请稍后重试。");
    setLoading(false);
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <div className="admin-page">
      <AdminPageHeader
        title="系统状态"
        description="查看平台核心服务、任务队列和模型能力的实时可用状态。"
        actions={
          <Button icon={<ReloadOutlined />} loading={loading} onClick={() => void load()}>
            刷新状态
          </Button>
        }
      />
      {error ? <Alert type="warning" showIcon title={error} /> : null}
      {loading ? (
        <Card className="admin-surface">
          <Skeleton active paragraph={{ rows: 5 }} />
        </Card>
      ) : (
        <>
          <section className="admin-status-grid" aria-label="平台服务状态">
            {services.map((service) => (
              <Card className="admin-surface" key={service.label}>
                <div className="admin-section-title">
                  <Typography.Title level={4}>{service.label}</Typography.Title>
                  {service.ready === true ? (
                    <CheckCircleOutlined style={{ color: "#16a34a", fontSize: 22 }} />
                  ) : (
                    <ExclamationCircleOutlined
                      style={{
                        color: service.ready === false ? "#f59e0b" : "#9ca3af",
                        fontSize: 22,
                      }}
                    />
                  )}
                </div>
                <Typography.Paragraph type="secondary">{service.description}</Typography.Paragraph>
                <Tag
                  color={
                    service.ready === true
                      ? "green"
                      : service.ready === false
                        ? "orange"
                        : "default"
                  }
                >
                  {service.ready === true
                    ? "运行正常"
                    : service.ready === false
                      ? "暂不可用或未配置"
                      : "暂未获取"}
                </Tag>
              </Card>
            ))}
          </section>
          <Card className="admin-surface" style={{ marginTop: 18 }}>
            <div className="admin-section-title">
              <Typography.Title level={4}>最近失败任务</Typography.Title>
            </div>
            {failedTasks.length ? (
              failedTasks.map((task) => (
                <div className="admin-list-row" key={task.id}>
                  <div className="admin-list-row__copy">
                    <strong>业务任务执行失败</strong>
                    <small>{new Date(task.created_at).toLocaleString("zh-CN")}</small>
                  </div>
                  <Tag color="red">需要处理</Tag>
                </div>
              ))
            ) : (
              <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无失败任务" />
            )}
          </Card>
        </>
      )}
    </div>
  );
}
