"use client";

import { Alert, Button, Card, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  cancelPlanApplication,
  getPlanApplications,
  type PlanApplication,
  type PlanApplicationStatus,
} from "@/lib/plans-client";
import { PLAN_APPLICATION_STATUS_LABELS } from "@/lib/product-copy";

const labels: Record<PlanApplicationStatus, string> = PLAN_APPLICATION_STATUS_LABELS;

export default function PlanApplicationsPage() {
  const [items, setItems] = useState<PlanApplication[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  const load = useCallback(async () => {
    try {
      const page = await getPlanApplications(1, status);
      setItems(page.results);
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [status]);
  useEffect(() => {
    let current = true;
    void getPlanApplications(1, status)
      .then((page) => {
        if (!current) return;
        setItems(page.results);
        setError("");
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      });
    return () => {
      current = false;
    };
  }, [status]);
  const cancel = async (application: PlanApplication) => {
    try {
      await cancelPlanApplication(application.id, application.version);
      await load();
    } catch (reason) {
      setError(userMessage(reason));
    }
  };
  return (
    <main className="page-shell">
      <Typography.Title>我的套餐申请</Typography.Title>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Space wrap>
          <Select
            aria-label="申请状态"
            value={status}
            onChange={setStatus}
            style={{ width: 160 }}
            options={[
              { value: "", label: "全部状态" },
              ...Object.entries(labels).map(([value, label]) => ({ value, label })),
            ]}
          />
          <Button onClick={() => void load()}>筛选</Button>
          <Button href="/">查看套餐</Button>
        </Space>
      </Card>
      <Table
        rowKey="id"
        dataSource={items}
        pagination={false}
        locale={{ emptyText: "暂时没有套餐申请。选择套餐并提交后，可在这里查看进度。" }}
        columns={[
          { title: "申请编号", dataIndex: "id" },
          {
            title: "套餐",
            render: (_, item) => String(item.public_plan_snapshot.name ?? "套餐"),
          },
          { title: "状态", render: (_, item) => <Tag>{labels[item.status]}</Tag> },
          {
            title: "操作",
            render: (_, item) => (
              <Space>
                <Link href={`/plan-applications/${item.id}`}>查看</Link>
                {(["pending", "contacted"] as string[]).includes(item.status) && (
                  <Button danger onClick={() => void cancel(item)}>
                    取消申请
                  </Button>
                )}
              </Space>
            ),
          },
        ]}
      />
    </main>
  );
}
