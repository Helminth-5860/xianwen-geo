"use client";

import { Alert, Button, Card, Col, Descriptions, Row, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  exportOperationsCustomers,
  getModerationQueue,
  getOperationsCustomers,
  getOperationsDashboard,
  getOperationsTasks,
  getReleaseReadiness,
  type ModerationQueue,
  type OperationsCustomer,
  type OperationsDashboard as DashboardData,
  type OperationsTask,
  type ReleaseReadiness,
} from "@/lib/operations-client";

const emptyModeration: ModerationQueue = { articles: [], images: [] };

export function OperationsDashboard() {
  const [dashboard, setDashboard] = useState<DashboardData | null>(null);
  const [readiness, setReadiness] = useState<ReleaseReadiness | null>(null);
  const [customers, setCustomers] = useState<OperationsCustomer[]>([]);
  const [tasks, setTasks] = useState<OperationsTask[]>([]);
  const [moderation, setModeration] = useState<ModerationQueue>(emptyModeration);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [exporting, setExporting] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [dashboardValue, readinessValue, customerPage, taskPage, moderationValue] =
        await Promise.all([
          getOperationsDashboard(),
          getReleaseReadiness(),
          getOperationsCustomers(),
          getOperationsTasks(),
          getModerationQueue(),
        ]);
      setDashboard(dashboardValue);
      setReadiness(readinessValue);
      setCustomers(customerPage.items);
      setTasks(taskPage.items);
      setModeration(moderationValue);
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

  const exportCustomers = useCallback(async () => {
    setExporting(true);
    setError("");
    try {
      const blob = await exportOperationsCustomers();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "customers.csv";
      document.body.append(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setExporting(false);
    }
  }, []);

  return (
    <main className="auth-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap>
          <Typography.Title level={2} style={{ margin: 0 }}>
            商用运营与发布就绪
          </Typography.Title>
          <Button onClick={() => void load()} loading={loading}>
            刷新安全状态
          </Button>
          <Button onClick={() => void exportCustomers()} loading={exporting}>
            导出脱敏客户 CSV
          </Button>
        </Space>
        {error ? (
          <Alert type="error" showIcon title="运营数据加载失败" description={error} />
        ) : null}
        {readiness ? (
          <Alert
            type={readiness.status === "READY" ? "success" : "warning"}
            showIcon
            title={`发布状态：${readiness.status}`}
            description="NOT_READY 表示外部部署证据尚未齐备，不代表代码测试失败。页面不会展示密钥或原始配置。"
          />
        ) : null}
        <Row gutter={[16, 16]}>
          <Col xs={24} md={12} lg={6}>
            <Card title="客户">
              <Typography.Title level={3}>{dashboard?.customers.total ?? "—"}</Typography.Title>
              <Typography.Text>正常 {dashboard?.customers.active ?? "—"}</Typography.Text>
            </Card>
          </Col>
          <Col xs={24} md={12} lg={6}>
            <Card title="待跟进">
              <Typography.Title level={3}>{dashboard?.followups.open ?? "—"}</Typography.Title>
              <Typography.Text type="danger">
                逾期 {dashboard?.followups.overdue ?? "—"}
              </Typography.Text>
            </Card>
          </Col>
          <Col xs={24} md={12} lg={6}>
            <Card title="待处理反馈">
              <Typography.Title level={3}>{dashboard?.feedback_open ?? "—"}</Typography.Title>
            </Card>
          </Col>
          <Col xs={24} md={12} lg={6}>
            <Card title="人工审核">
              <Typography.Title level={3}>
                {(dashboard?.moderation.articles ?? 0) + (dashboard?.moderation.images ?? 0)}
              </Typography.Title>
              <Typography.Text>
                文章 {moderation.articles.length} / 图片 {moderation.images.length}
              </Typography.Text>
            </Card>
          </Col>
        </Row>
        <Card title="Release readiness（安全摘要）">
          <Descriptions bordered size="small" column={{ xs: 1, md: 2 }}>
            {(readiness?.checks ?? []).map((check) => (
              <Descriptions.Item key={check.key} label={check.key}>
                <Tag color={check.status === "READY" ? "green" : "orange"}>{check.status}</Tag>
                <Typography.Text code>{check.code}</Typography.Text>
              </Descriptions.Item>
            ))}
          </Descriptions>
        </Card>
        <Card title="客户运营档案">
          <Table
            rowKey="id"
            loading={loading}
            dataSource={customers}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: "客户", dataIndex: "nickname" },
              { title: "手机号", dataIndex: "phone" },
              { title: "账号", dataIndex: "account_status" },
              {
                title: "客户状态",
                render: (_, row) => row.profile.status?.name ?? "未设置",
              },
              { title: "主体", dataIndex: "subject_count" },
              { title: "待跟进", dataIndex: "open_followup_count" },
            ]}
          />
        </Card>
        <Card title="任务中心（无正文安全投影）">
          <Table
            rowKey={(row) => `${row.type}:${row.id}`}
            loading={loading}
            dataSource={tasks}
            pagination={{ pageSize: 10 }}
            columns={[
              { title: "类型", dataIndex: "type" },
              { title: "状态", dataIndex: "status" },
              { title: "安全错误码", dataIndex: "safe_error_code" },
              { title: "创建时间", dataIndex: "created_at" },
            ]}
          />
        </Card>
      </Space>
    </main>
  );
}
