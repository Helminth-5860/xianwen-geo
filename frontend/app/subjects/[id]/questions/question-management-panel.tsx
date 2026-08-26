"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Pagination,
  Popconfirm,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useCallback, useEffect, useState } from "react";

import { AuthApiError, userMessage } from "@/lib/auth-client";
import {
  getCurrentQuestionBank,
  removeCurrentQuestionBankItems,
  type QuestionBankVersion,
  type QuestionBankVersionItem,
} from "@/lib/question-bank-client";

const QUESTION_PAGE_SIZE = 20;

export default function QuestionManagementPanel({ subjectId }: Readonly<{ subjectId: string }>) {
  const [version, setVersion] = useState<QuestionBankVersion>();
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);
  const [removing, setRemoving] = useState(false);
  const [selectedIds, setSelectedIds] = useState<ReadonlySet<string>>(new Set());
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  const reload = useCallback(async () => {
    setLoading(true);
    setNotice("");
    try {
      const next = await getCurrentQuestionBank(subjectId);
      setVersion(next);
      setPage(1);
      setSelectedIds(new Set());
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
  const visibleIds = visibleItems.map((item) => item.id);
  const selectedVisibleCount = visibleIds.filter((id) => selectedIds.has(id)).length;
  const allVisibleSelected = visibleIds.length > 0 && selectedVisibleCount === visibleIds.length;

  function toggleQuestion(questionId: string, checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (checked) next.add(questionId);
      else next.delete(questionId);
      return next;
    });
  }

  function toggleVisible(checked: boolean) {
    setSelectedIds((current) => {
      const next = new Set(current);
      for (const id of visibleIds) {
        if (checked) next.add(id);
        else next.delete(id);
      }
      return next;
    });
  }

  async function removeSelected() {
    if (!version || selectedIds.size === 0) return;
    setRemoving(true);
    setError("");
    setNotice("");
    try {
      const result = await removeCurrentQuestionBankItems(subjectId, {
        expectedVersionId: version.id,
        questionIds: [...selectedIds],
      });
      await reload();
      setNotice(`已删除 ${result.removed_count} 条问题，历史检测记录不受影响`);
    } catch (reason) {
      if (reason instanceof AuthApiError) {
        const messages: Readonly<Record<string, string>> = {
          QUESTION_BANK_VERSION_CONFLICT: "问题库已发生变化，请刷新后重新选择",
          QUESTION_BANK_INPUT_CONFLICT: "主体资料或关键词资产已变化，请先重新生成问题库",
          QUESTION_BANK_VALUES_INVALID: "选择的问题无效，请刷新后重试",
        };
        setError(messages[reason.code] ?? userMessage(reason));
      } else {
        setError(userMessage(reason));
      }
    } finally {
      setRemoving(false);
    }
  }

  return (
    <Card title="正式问题库" style={{ marginTop: 20 }}>
      <Space direction="vertical" size="middle" style={{ width: "100%" }}>
        {error ? <Alert type="warning" showIcon message={error} /> : null}
        {notice ? <Alert type="success" showIcon message={notice} /> : null}
        {!version ? (
          <Button href={`/subjects/${subjectId}/questions`} type="primary">
            去生成问题
          </Button>
        ) : null}
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
            <Space wrap>
              <Checkbox
                aria-label="全选本页问题"
                checked={allVisibleSelected}
                disabled={removing || visibleIds.length === 0}
                indeterminate={selectedVisibleCount > 0 && !allVisibleSelected}
                onChange={(event) => toggleVisible(event.target.checked)}
              >
                全选本页
              </Checkbox>
              <Typography.Text type="secondary">已选择 {selectedIds.size} 条</Typography.Text>
              <Popconfirm
                title="确认删除所选问题？"
                description="系统会生成不包含这些问题的新正式版本，历史检测记录不会被删除。"
                okText="确认删除"
                cancelText="取消"
                okButtonProps={{ danger: true, loading: removing }}
                onConfirm={removeSelected}
              >
                <Button danger disabled={selectedIds.size === 0} loading={removing}>
                  批量删除
                </Button>
              </Popconfirm>
            </Space>
            {visibleItems.map((item) => (
              <Card key={item.id} size="small">
                <Space align="start" size="middle" style={{ width: "100%" }}>
                  <Checkbox
                    aria-label={`选择问题-${item.id}`}
                    checked={selectedIds.has(item.id)}
                    disabled={removing}
                    onChange={(event) => toggleQuestion(item.id, event.target.checked)}
                  />
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
