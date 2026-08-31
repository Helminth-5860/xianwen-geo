"use client";

import { Alert, Card, Empty, Select, Spin, Table, Tag, Typography } from "antd";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  CUSTOMER_QUOTA_PRESENTATION,
  CUSTOMER_QUOTA_TYPES,
  customerQuotaPresentation,
  customerQuotaType,
  formatQuotaAmount,
  getUserQuotaLedger,
  type UserQuotaLedgerEntry,
} from "@/lib/quota-client";
import { safeLocalProductMessage } from "@/lib/product-copy";

import styles from "../subscription.module.css";

const LEDGER_ACTIONS: Readonly<
  Record<
    string,
    {
      label: string;
      verb: string;
      status: string;
      color: string;
      direction: "increase" | "decrease";
    }
  >
> = {
  consume: {
    label: "任务已完成",
    verb: "消耗",
    status: "已完成",
    color: "green",
    direction: "decrease",
  },
  release: {
    label: "未使用额度已退回",
    verb: "返还",
    status: "已退回",
    color: "blue",
    direction: "increase",
  },
  grant: {
    label: "额度已增加",
    verb: "增加",
    status: "已完成",
    color: "green",
    direction: "increase",
  },
  compensate: {
    label: "额度已补发",
    verb: "补发",
    status: "已完成",
    color: "green",
    direction: "increase",
  },
  refund: {
    label: "额度已返还",
    verb: "返还",
    status: "已完成",
    color: "green",
    direction: "increase",
  },
  manual_deduct: {
    label: "额度已扣减",
    verb: "扣减",
    status: "已完成",
    color: "gold",
    direction: "decrease",
  },
  "manual-deduct": {
    label: "额度已扣减",
    verb: "扣减",
    status: "已完成",
    color: "gold",
    direction: "decrease",
  },
};

const CUSTOMER_LEDGER_ACTIONS = new Set(Object.keys(LEDGER_ACTIONS));

function customerLedgerItems(items: readonly UserQuotaLedgerEntry[]) {
  return items.filter(
    (item) =>
      customerQuotaType(item.quota_type) !== null && CUSTOMER_LEDGER_ACTIONS.has(item.action),
  );
}

function formatDate(value: string) {
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function ledgerAmount(entry: UserQuotaLedgerEntry) {
  if (typeof entry.amount === "number") return Math.abs(entry.amount);
  if (typeof entry.change_amount === "number") return Math.abs(entry.change_amount);
  if (entry.action === "consume" || entry.action === "release") {
    return Math.abs(entry.frozen_delta || entry.available_delta);
  }
  return Math.abs(entry.available_delta || entry.frozen_delta);
}

function balanceBefore(entry: UserQuotaLedgerEntry) {
  return (
    entry.balance_before ?? entry.available_before ?? entry.available_after - entry.available_delta
  );
}

function balanceAfter(entry: UserQuotaLedgerEntry) {
  return entry.balance_after ?? entry.available_after;
}

export default function QuotaUsagePage() {
  const [items, setItems] = useState<UserQuotaLedgerEntry[]>([]);
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [quotaFilter, setQuotaFilter] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async (nextPage = 1, quotaType = "") => {
    setLoading(true);
    setError("");
    try {
      const data = await getUserQuotaLedger(nextPage, quotaType);
      setItems(customerLedgerItems(data.results));
      setTotal(data.pagination.count);
      setPage(data.pagination.page);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    let active = true;
    void getUserQuotaLedger(1, "")
      .then((data) => {
        if (!active) return;
        setItems(customerLedgerItems(data.results));
        setTotal(data.pagination.count);
        setPage(data.pagination.page);
      })
      .catch((reason) => {
        if (active) setError(userMessage(reason));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  return (
    <main className={styles.page}>
      <header className={styles.pageHeader}>
        <Link href="/subscription">← 返回套餐与额度</Link>
        <Typography.Title className={styles.usageTitle}>额度使用记录</Typography.Title>
        <Typography.Paragraph type="secondary">
          查看各项功能的实际使用、返还和人工调整记录。
        </Typography.Paragraph>
      </header>

      {error ? (
        <Alert
          type="warning"
          showIcon
          title="额度使用记录暂时无法显示"
          description="请稍后刷新页面重新查看。"
          className={styles.section}
        />
      ) : null}

      <Card className={styles.section}>
        <Select
          aria-label="按功能筛选额度记录"
          value={quotaFilter}
          className={styles.usageFilter}
          options={[
            { value: "", label: "全部功能" },
            ...CUSTOMER_QUOTA_TYPES.map((quotaType) => ({
              value: quotaType,
              label: CUSTOMER_QUOTA_PRESENTATION[quotaType].name,
            })),
          ]}
          onChange={(value) => {
            setQuotaFilter(value);
            void load(1, value);
          }}
        />
        {loading && !items.length ? (
          <div className={styles.usageLoading}>
            <Spin description="正在加载额度使用记录" />
          </div>
        ) : (
          <Table<UserQuotaLedgerEntry>
            rowKey="id"
            loading={loading}
            dataSource={items}
            scroll={{ x: 920 }}
            locale={{
              emptyText: (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="暂无额度使用记录" />
              ),
            }}
            pagination={{
              current: page,
              pageSize: 20,
              total,
              showSizeChanger: false,
              onChange: (nextPage) => void load(nextPage, quotaFilter),
            }}
            columns={[
              { title: "时间", render: (_, item) => formatDate(item.created_at), width: 170 },
              {
                title: "功能",
                render: (_, item) => customerQuotaPresentation(item.quota_type)?.name ?? "套餐额度",
                width: 140,
              },
              {
                title: "操作说明",
                render: (_, item) =>
                  safeLocalProductMessage(
                    item.description ?? item.safe_reason ?? "",
                    item.action_label ?? LEDGER_ACTIONS[item.action]?.label ?? "额度发生变化",
                  ),
              },
              {
                title: "额度变化",
                render: (_, item) => {
                  const action = LEDGER_ACTIONS[item.action];
                  const unit =
                    item.unit_display_name ??
                    customerQuotaPresentation(item.quota_type)?.unit ??
                    "";
                  return `${action?.verb ?? "调整"} ${formatQuotaAmount(ledgerAmount(item))} ${unit}`;
                },
                width: 140,
              },
              {
                title: "变化前",
                render: (_, item) => formatQuotaAmount(balanceBefore(item)),
                width: 110,
              },
              {
                title: "变化后",
                render: (_, item) => formatQuotaAmount(balanceAfter(item)),
                width: 110,
              },
              {
                title: "状态",
                render: (_, item) => {
                  const action = LEDGER_ACTIONS[item.action];
                  return (
                    <Tag color={action?.color ?? "default"}>
                      {item.status_label ?? action?.status ?? "已完成"}
                    </Tag>
                  );
                },
                width: 100,
              },
            ]}
          />
        )}
      </Card>
    </main>
  );
}
