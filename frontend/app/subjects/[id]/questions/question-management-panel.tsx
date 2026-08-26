"use client";

import { Alert, Button, Card, Pagination, Space, Spin, Tag, Typography } from "antd";
import { useCallback, useEffect, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  getCurrentQuestionBank,
  type QuestionBankVersion,
  type QuestionBankVersionItem,
} from "@/lib/question-bank-client";

const QUESTION_PAGE_SIZE = 20;

export default function QuestionManagementPanel({ subjectId }: Readonly<{ subjectId: string }>) {
  const [version, setVersion] = useState<QuestionBankVersion>();
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    try {
      const next = await getCurrentQuestionBank(subjectId);
      setVersion(next);
      setPage(1);
      setError("");
    } catch (reason) {
      setVersion(undefined);
      setError(
        reason instanceof AuthApiError && reason.status === 404
          ? "暂无正式问题库，请先完成问题生成"
          : userMessage(reason),
      );
    } finally {
      setLoading(false);
    }
  }, [subjectId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void reload(), 0);
    return () => window.clearTimeout(timer);
  }, [reload]);

  if (loading) return <Spin description="正在加载问题管理" />;

  const items: ReadonlyArray<QuestionBankVersionItem> = version?.items ?? [];
  const pageCount = Math.max(1, Math.ceil(items.length / QUESTION_PAGE_SIZE));
  const effectivePage = Math.min(page, pageCount);
  const pageStart = (effectivePage - 1) * QUESTION_PAGE_SIZE;
  const visibleItems = items.slice(pageStart, pageStart + QUESTION_PAGE_SIZE);

  return (
    <Card title="正式问题库" style={{ marginTop: 20 }}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {error ? <Alert type="warning" showIcon message={error} /> : null}
        {version ? (
          <>
            <Space wrap>
              <Tag color="green">正式版本 v{version.version_no}</Tag>
              <Tag>问题数量 {version.item_count}</Tag>
              <Button href="/geo/detections" type="primary">
                去主体检测
              </Button>
              <Button href={`/subjects/${subjectId}/questions`}>重新生成问题</Button>
            </Space>
            {visibleItems.map((item) => (
              <Card key={item.id} size="small">
                <Space direction="vertical" size="small" style={{ width: "100%" }}>
                  <Typography.Text strong>{item.text}</Typography.Text>
                  <Space wrap>
                    <Tag>
                      {item.priority === "high"
                        ? "高优先级"
                        : item.priority === "low"
                          ? "低优先级"
                          : "中优先级"}
                    </Tag>
                    <Tag>
                      {item.question_type === "brand_directed" ? "品牌指向型" : "自然探索型"}
                    </Tag>
                    <Tag color={item.participates_in_scoring ? "green" : "default"}>
                      {item.participates_in_scoring ? "参与检测" : "不参与检测"}
                    </Tag>
                  </Space>
                </Space>
              </Card>
            ))}
            {items.length > QUESTION_PAGE_SIZE ? (
              <Pagination
                aria-label="问题管理分页"
                current={effectivePage}
                pageSize={QUESTION_PAGE_SIZE}
                total={items.length}
                showSizeChanger={false}
                showTotal={(total, range) => `第 ${range[0]}-${range[1]} 条，共 ${total} 条`}
                onChange={setPage}
              />
            ) : null}
          </>
        ) : null}
      </Space>
    </Card>
  );
}
