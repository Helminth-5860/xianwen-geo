"use client";

import { Alert, Button, Card, Empty, List, Modal, Pagination, Space, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { getContentLibrary, type Article } from "@/lib/articles-client";
import { userMessage } from "@/lib/auth-client";

const PAGE_SIZE = 20;

type Props = Readonly<{ subjectId: string }>;

function statusLabel(status: Article["status"]) {
  return {
    draft: "草稿",
    generating: "生成中",
    reviewing: "审核中",
    ready: "可用",
    rejected: "未通过",
  }[status];
}

export default function ContentLibrary({ subjectId }: Props) {
  const [items, setItems] = useState<Article[]>([]);
  const [page, setPage] = useState(1);
  const [count, setCount] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [preview, setPreview] = useState<Article>();

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const result = await getContentLibrary(subjectId, page);
      setItems(result.items);
      setCount(result.pagination.count);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, [page, subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <main className="page-shell">
      <Space orientation="vertical" size="large" style={{ width: "100%" }}>
        <Space wrap align="baseline">
          <Typography.Title level={2}>内容库</Typography.Title>
          <Link href={`/subjects/${subjectId}/articles/new`}>生成新文章</Link>
        </Space>
        <Typography.Text type="secondary">
          这里保存你明确加入内容库的文章，每页显示 20 篇。
        </Typography.Text>
        {error && <Alert type="error" showIcon title={error} />}
        <Card title={`已保存文章 ${count} 篇`}>
          <List
            loading={loading}
            dataSource={items}
            locale={{
              emptyText: (
                <Empty description="还没有文章，生成并保存到内容库后会出现在这里。">
                  <Button type="primary" href={`/subjects/${subjectId}/articles/new`}>
                    生成第一篇文章
                  </Button>
                </Empty>
              ),
            }}
            renderItem={(item) => (
              <List.Item
                actions={[
                  <Button key="preview" onClick={() => setPreview(item)}>
                    查看全文
                  </Button>,
                ]}
              >
                <List.Item.Meta
                  title={item.title || "未命名文章"}
                  description={
                    <Space orientation="vertical" size={4}>
                      <Space wrap>
                        <Tag color={item.status === "ready" ? "green" : "blue"}>
                          {statusLabel(item.status)}
                        </Tag>
                        {item.article_type?.name && <Tag>{item.article_type.name}</Tag>}
                        <Typography.Text type="secondary">
                          保存于{" "}
                          {item.autosaved_at ? new Date(item.autosaved_at).toLocaleString() : "-"}
                        </Typography.Text>
                      </Space>
                      <Typography.Paragraph ellipsis={{ rows: 2 }} style={{ marginBottom: 0 }}>
                        {item.content}
                      </Typography.Paragraph>
                    </Space>
                  }
                />
              </List.Item>
            )}
          />
          {count > PAGE_SIZE && (
            <Pagination
              current={page}
              pageSize={PAGE_SIZE}
              total={count}
              showSizeChanger={false}
              onChange={setPage}
            />
          )}
        </Card>
      </Space>

      <Modal
        open={Boolean(preview)}
        title={preview?.title || "未命名文章"}
        width={860}
        footer={<Button onClick={() => setPreview(undefined)}>关闭</Button>}
        onCancel={() => setPreview(undefined)}
      >
        <Typography.Paragraph style={{ whiteSpace: "pre-wrap" }}>
          {preview?.content}
        </Typography.Paragraph>
      </Modal>
    </main>
  );
}
