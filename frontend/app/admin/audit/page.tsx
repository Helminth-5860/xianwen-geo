"use client";

import {
  Alert,
  Button,
  Card,
  Descriptions,
  Input,
  Pagination,
  Space,
  Table,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { userMessage, type PageData } from "@/lib/auth-client";
import { getAuditEvent, getAuditEvents, type AuditEvent } from "@/lib/risk-client";

export default function AuditPage() {
  const [data, setData] = useState<PageData<AuditEvent> | null>(null);
  const [selected, setSelected] = useState<AuditEvent | null>(null);
  const [actionKey, setActionKey] = useState("");
  const [outcome, setOutcome] = useState("");
  const [page, setPage] = useState(1);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    void getAuditEvents(page, actionKey, outcome)
      .then(setData)
      .catch((reason) => setError(userMessage(reason)));
  }, [actionKey, outcome, page]);
  useEffect(load, [load]);
  return (
    <main className="admin-page">
      <Typography.Title>统一安全审计</Typography.Title>
      <Alert
        type="info"
        showIcon
        message="仅展示白名单安全摘要"
        description="不展示完整 payload、手机号、IP、密码、Cookie、原始异常或基础设施秘密。"
      />
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Space>
          <Input
            aria-label="动作筛选"
            value={actionKey}
            placeholder="动作 key"
            onChange={(event) => setActionKey(event.target.value)}
          />
          <Input
            aria-label="结果筛选"
            value={outcome}
            placeholder="结果"
            onChange={(event) => setOutcome(event.target.value)}
          />
        </Space>
        <Table
          rowKey="id"
          pagination={false}
          dataSource={data?.results ?? []}
          columns={[
            { title: "动作", dataIndex: "action_key" },
            { title: "结果", dataIndex: "outcome" },
            { title: "目标类型", dataIndex: "target_type" },
            {
              title: "时间",
              dataIndex: "created_at",
              render: (value) => new Date(value).toLocaleString("zh-CN"),
            },
            {
              title: "操作",
              render: (_, item) => (
                <Button
                  type="link"
                  onClick={() =>
                    void getAuditEvent(item.id)
                      .then(setSelected)
                      .catch((reason) => setError(userMessage(reason)))
                  }
                >
                  安全详情
                </Button>
              ),
            },
          ]}
        />
        <Pagination
          current={page}
          pageSize={data?.pagination.page_size ?? 20}
          total={data?.pagination.count ?? 0}
          showSizeChanger={false}
          onChange={setPage}
        />
      </Card>
      {selected && (
        <Card title="审计安全详情">
          <Descriptions bordered column={1}>
            <Descriptions.Item label="请求 ID">{selected.request_id}</Descriptions.Item>
            <Descriptions.Item label="动作">{selected.action_key}</Descriptions.Item>
            <Descriptions.Item label="执行前">
              {JSON.stringify(selected.safe_before)}
            </Descriptions.Item>
            <Descriptions.Item label="执行后">
              {JSON.stringify(selected.safe_after)}
            </Descriptions.Item>
            <Descriptions.Item label="稳定错误码">
              {selected.stable_error_code || "无"}
            </Descriptions.Item>
          </Descriptions>
        </Card>
      )}
    </main>
  );
}
