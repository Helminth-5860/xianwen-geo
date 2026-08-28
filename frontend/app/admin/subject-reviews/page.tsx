"use client";

import { Alert, Button, Card, Select, Space, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getSubjectReviews, type SubjectReview } from "@/lib/subject-risk-client";

const STATUS_LABELS: Record<SubjectReview["status"], string> = {
  pending: "\u5f85\u5ba1\u6838",
  approved: "\u5df2\u901a\u8fc7",
  rejected: "\u5df2\u62d2\u7edd",
  superseded: "\u5df2\u88ab\u65b0\u7248\u672c\u66ff\u4ee3",
};

export default function SubjectReviewListPage() {
  const [rows, setRows] = useState<SubjectReview[]>([]);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(
    () =>
      getSubjectReviews(1, status)
        .then((result) => setRows(result.results))
        .catch((reason) => setError(userMessage(reason))),
    [status],
  );

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <main className="admin-page">
      <Typography.Title>{"\u4e3b\u4f53\u8d44\u6599\u5ba1\u6838"}</Typography.Title>
      <Typography.Paragraph>
        <Link href="/admin/subject-risk">{"\u7ef4\u62a4\u98ce\u9669\u76ee\u5f55\u8349\u7a3f"}</Link>
      </Typography.Paragraph>
      {error && <Alert type="error" showIcon message={error} />}
      <Card>
        <Space>
          <Select
            aria-label={"\u5ba1\u6838\u72b6\u6001"}
            value={status}
            onChange={setStatus}
            style={{ width: 180 }}
            options={[
              { value: "", label: "\u5168\u90e8" },
              ...Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label })),
            ]}
          />
          <Button onClick={() => void load()}>{"\u5237\u65b0"}</Button>
        </Space>
      </Card>
      <Table
        rowKey="id"
        dataSource={rows}
        pagination={false}
        columns={[
          { title: "\u4e3b\u4f53", dataIndex: "official_name" },
          { title: "\u8d44\u6599\u7248\u672c", dataIndex: "version_no" },
          {
            title: "\u72b6\u6001",
            render: (_, item) => (
              <Tag color={item.status === "pending" ? "orange" : "default"}>
                {STATUS_LABELS[item.status]}
              </Tag>
            ),
          },
          {
            title: "\u547d\u4e2d\u539f\u56e0",
            render: (_, item) => item.reason_types.join(", "),
          },
          {
            title: "\u64cd\u4f5c",
            render: (_, item) => (
              <Link href={`/admin/subject-reviews/${item.id}`}>{"\u67e5\u770b"}</Link>
            ),
          },
        ]}
      />
    </main>
  );
}
