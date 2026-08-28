"use client";

import {
  ArrowRightOutlined,
  CheckCircleOutlined,
  ClockCircleOutlined,
  CloseCircleOutlined,
  PlayCircleOutlined,
  ReloadOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, Empty, Modal, Progress, Space, Spin, Tag, Typography } from "antd";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getExecutionPlan,
  updateExecutionPlan,
  type ExecutionPlan,
  type ExecutionPlanAction,
  type ExecutionPlanItem,
} from "@/lib/strategy-execution-client";

import styles from "../execution-page.module.css";

const planStatusLabels = {
  active: { text: "执行中", color: "processing" },
  completed: { text: "已完成", color: "success" },
  cancelled: { text: "已取消", color: "error" },
} as const;

function statusOf(plan: ExecutionPlan) {
  const hasCompleted = plan.items.some((item) => item.status === "completed");
  const hasCancelled = plan.items.some((item) => item.status === "cancelled");
  if (plan.status === "cancelled" && hasCompleted && hasCancelled) {
    return { text: "部分完成", color: "warning" } as const;
  }
  return planStatusLabels[plan.status];
}

const itemStatusLabels = {
  pending: { text: "待开始", color: "default" },
  in_progress: { text: "进行中", color: "processing" },
  completed: { text: "已完成", color: "success" },
  cancelled: { text: "已取消", color: "error" },
} as const;

const mediaStatusLabels = {
  not_submitted: "待提交",
  pending: "已提交管理员",
  contacted: "管理员已联系",
  completed: "已完成",
  cancelled: "已取消",
} as const;

function priceText(value: number) {
  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "CNY",
    maximumFractionDigits: 2,
  }).format(Math.max(0, value) / 100);
}

function ItemActions({
  item,
  disabled,
  onAction,
}: Readonly<{
  item: ExecutionPlanItem;
  disabled: boolean;
  onAction: (action: ExecutionPlanAction) => void;
}>) {
  if (item.status === "completed") {
    return item.route ? (
      <Button href={item.route}>
        查看相关页面 <ArrowRightOutlined />
      </Button>
    ) : null;
  }
  if (item.status === "cancelled") {
    return (
      <Button
        disabled={disabled || item.kind === "paid_media"}
        icon={<ReloadOutlined />}
        onClick={() => onAction("restore_item")}
      >
        恢复
      </Button>
    );
  }
  return (
    <Space wrap>
      {item.route ? (
        <Button href={item.route}>
          前往处理 <ArrowRightOutlined />
        </Button>
      ) : null}
      {item.status === "pending" ? (
        <Button
          type="primary"
          disabled={disabled}
          icon={<PlayCircleOutlined />}
          onClick={() => onAction("start_item")}
        >
          开始执行
        </Button>
      ) : null}
      <Button
        disabled={disabled}
        icon={<CheckCircleOutlined />}
        onClick={() => onAction("complete_item")}
      >
        标记完成
      </Button>
      <Button
        danger
        disabled={disabled}
        icon={<CloseCircleOutlined />}
        onClick={() => onAction("cancel_item")}
      >
        取消此项
      </Button>
    </Space>
  );
}

export default function ExecutionPlanDetailPage({ planId }: Readonly<{ planId: string }>) {
  const router = useRouter();
  const { currentSubject, loading: subjectLoading } = useSubjectWorkspace();
  const [plan, setPlan] = useState<ExecutionPlan>();
  const [busyKey, setBusyKey] = useState("");
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    if (subjectLoading) return;
    try {
      const next = await getExecutionPlan(planId);
      if (!currentSubject || next.subject_id !== currentSubject.id) {
        router.replace("/geo/execution");
        return;
      }
      setPlan(next);
      setError("");
    } catch (reason) {
      setError(userMessage(reason));
    }
  }, [currentSubject, planId, router, subjectLoading]);

  useEffect(() => {
    if (subjectLoading) return;
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load, subjectLoading]);

  const applyAction = async (action: ExecutionPlanAction, itemKey?: string) => {
    if (!plan || busyKey) return;
    setBusyKey(itemKey ?? action);
    setError("");
    try {
      const next = await updateExecutionPlan(plan.id, {
        action,
        ...(itemKey ? { item_key: itemKey } : {}),
        expected_version: plan.version,
      });
      setPlan(next);
    } catch (reason) {
      setError(userMessage(reason));
      await load();
    } finally {
      setBusyKey("");
    }
  };

  const cancelPlan = () => {
    if (!plan || busyKey) return;
    Modal.confirm({
      title: "确认取消整个执行计划？",
      content: "尚未完成的行动会被取消。已进入处理阶段的媒体申请可能需要先联系管理员。",
      okText: "确认取消",
      cancelText: "暂不取消",
      okButtonProps: { danger: true },
      onOk: () => applyAction("cancel_plan"),
    });
  };

  const completedCount = useMemo(
    () => plan?.items.filter((item) => item.status === "completed").length ?? 0,
    [plan],
  );
  const progress = plan?.items.length ? Math.round((completedCount / plan.items.length) * 100) : 0;
  const actionsBeforeRetest = plan?.items.filter((item) => item.key !== "retest") ?? [];
  const canRetest =
    actionsBeforeRetest.length > 0 &&
    actionsBeforeRetest.every((item) => item.status === "completed");

  if (subjectLoading || (!plan && !error))
    return <Spin fullscreen description="正在加载执行计划" />;

  if (!plan) {
    return (
      <main className={styles.page}>
        <Alert type="error" showIcon message={error || "未找到执行计划"} />
        <Button href="/geo/execution">返回执行计划</Button>
      </main>
    );
  }

  const status = statusOf(plan);
  const locked = plan.status === "completed";

  return (
    <main className={styles.page}>
      <header className={styles.header}>
        <div>
          <Typography.Text type="secondary">执行计划</Typography.Text>
          <Typography.Title level={2}>{plan.package_name}</Typography.Title>
          <Typography.Paragraph type="secondary">
            按步骤完成并记录行动，全部完成后可发起复测查看真实变化。
          </Typography.Paragraph>
        </div>
        <Space wrap>
          <Button href={`/geo/strategy/${plan.report_id}`}>查看原优化方案</Button>
          <Button href="/geo/execution">返回计划列表</Button>
        </Space>
      </header>

      {error ? <Alert type="error" showIcon message={error} /> : null}

      <section className={styles.subjectBar}>
        <div>
          <Typography.Text type="secondary">当前主体</Typography.Text>
          <Typography.Title level={3}>
            {currentSubject?.official_name || currentSubject?.subject_type.name}
          </Typography.Title>
        </div>
        <Tag color={status.color}>{status.text}</Tag>
      </section>

      <div className={styles.detailGrid}>
        <div>
          <Card
            title="行动步骤"
            extra={
              <Tag>
                {completedCount} / {plan.items.length} 已完成
              </Tag>
            }
          >
            {plan.items.length === 0 ? (
              <Empty description="当前计划没有行动步骤" />
            ) : (
              <div className={styles.itemList}>
                {plan.items.map((item, index) => {
                  const itemStatus = itemStatusLabels[item.status];
                  return (
                    <article className={styles.itemCard} data-status={item.status} key={item.key}>
                      <div className={styles.itemHeader}>
                        <Space wrap>
                          <Typography.Text type="secondary">第 {index + 1} 项</Typography.Text>
                          <strong>{item.title}</strong>
                          <Tag color={itemStatus.color}>{itemStatus.text}</Tag>
                        </Space>
                        {item.period ? (
                          <Tag icon={<ClockCircleOutlined />}>{item.period}</Tag>
                        ) : null}
                      </div>
                      <p>{item.recommendation}</p>
                      <div className={styles.itemDetails}>
                        <div>
                          <span>交付结果</span>
                          {item.deliverables.join("；")}
                        </div>
                        <div>
                          <span>完成标准</span>
                          {item.success_metric}
                        </div>
                        <div>
                          <span>费用说明</span>
                          {item.cost_note}
                        </div>
                      </div>
                      <ItemActions
                        item={item}
                        disabled={locked || Boolean(busyKey)}
                        onAction={(action) => void applyAction(action, item.key)}
                      />
                    </article>
                  );
                })}
              </div>
            )}
          </Card>
        </div>

        <aside className={styles.summaryPanel}>
          <Card title="执行进度">
            <div className={styles.progressHeader}>
              <span>总体完成度</span>
              <strong>{progress}%</strong>
            </div>
            <Progress
              percent={progress}
              status={status.text === "已取消" ? "exception" : undefined}
            />
            <div className={styles.summaryNumbers}>
              <div>
                <span>行动项目</span>
                <strong>{plan.items.length}</strong>
              </div>
              <div>
                <span>预计周期</span>
                <strong>{plan.estimated_days} 天</strong>
              </div>
              <div>
                <span>推荐媒体</span>
                <strong>{plan.selected_media.length} 家</strong>
              </div>
              <div>
                <span>媒体参考费用</span>
                <strong>{priceText(plan.estimated_price_cents)}</strong>
              </div>
            </div>
          </Card>

          {plan.selected_media.length > 0 ? (
            <Card title="媒体申请">
              <Alert
                type="info"
                showIcon
                message="媒体申请已提交管理员，确认前不会自动付款或发布。"
              />
              <div className={styles.mediaList}>
                {plan.selected_media.map((media) => (
                  <div className={styles.mediaRow} key={media.id}>
                    <div className={styles.mediaInfo}>
                      <strong>{media.name}</strong>
                      <span>{mediaStatusLabels[media.inquiry_status]}</span>
                    </div>
                    <strong>{priceText(media.price_cents)}</strong>
                  </div>
                ))}
              </div>
              <Button block href={`/subjects/${plan.subject_id}/paid-media`}>
                查看媒体申请
              </Button>
            </Card>
          ) : null}

          <Card title="完成后验证">
            <Typography.Paragraph type="secondary">
              完成主要行动后，使用同一主体再次检测，查看曝光、提及和推荐表现是否真实改善。
            </Typography.Paragraph>
            <Button
              type="primary"
              block
              href={`/geo/retest?report_id=${plan.report_id}`}
              disabled={!canRetest}
            >
              发起复测 <ArrowRightOutlined />
            </Button>
          </Card>

          {plan.status === "active" ? (
            <Card title="计划管理" className={styles.dangerZone}>
              <Button danger block loading={busyKey === "cancel_plan"} onClick={cancelPlan}>
                取消整个计划
              </Button>
            </Card>
          ) : null}
        </aside>
      </div>
    </main>
  );
}
