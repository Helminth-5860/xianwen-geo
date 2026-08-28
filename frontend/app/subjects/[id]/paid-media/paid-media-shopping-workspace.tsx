"use client";

import {
  CheckCircleOutlined,
  ExportOutlined,
  SearchOutlined,
  ShoppingCartOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Checkbox,
  Empty,
  Input,
  Modal,
  Pagination,
  Skeleton,
  Space,
  Typography,
  message,
} from "antd";
import Image from "next/image";
import { useEffect, useMemo, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import { getPaidMediaExternalUrl, getPaidMediaLogoFallback } from "@/lib/paid-media-catalog";
import {
  createPaidMediaInquiry,
  getPaidMediaCatalog,
  type PaidMediaCatalogItem,
} from "@/lib/paid-media-client";

import styles from "./paid-media-shopping-workspace.module.css";

const { Paragraph, Text, Title } = Typography;

export const PAID_MEDIA_PAGE_SIZE = 20;
export const PAID_MEDIA_SELECTION_LIMIT = 200;

const priceFormatter = new Intl.NumberFormat("zh-CN", {
  style: "currency",
  currency: "CNY",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

function formatPrice(priceCents: number) {
  return priceFormatter.format(priceCents / 100);
}

function MediaLogo({ item }: Readonly<{ item: PaidMediaCatalogItem }>) {
  const [failed, setFailed] = useState(false);

  if (!item.logo_path || failed) {
    return (
      <span className={styles.logoFallback} aria-hidden="true">
        {getPaidMediaLogoFallback(item.name)}
      </span>
    );
  }

  return (
    <Image
      className={styles.logoImage}
      src={item.logo_path}
      alt={`${item.name}标识`}
      width={46}
      height={46}
      onError={() => setFailed(true)}
    />
  );
}

export function PaidMediaShoppingWorkspace({ subjectId }: Readonly<{ subjectId: string }>) {
  const [messageApi, messageHolder] = message.useMessage();
  const [query, setQuery] = useState("");
  const [debouncedQuery, setDebouncedQuery] = useState("");
  const [page, setPage] = useState(1);
  const [items, setItems] = useState<PaidMediaCatalogItem[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedItems, setSelectedItems] = useState(() => new Map<string, PaidMediaCatalogItem>());
  const [loadedRequestKey, setLoadedRequestKey] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const requestKey = `${debouncedQuery}\u0000${page}`;
  const loading = loadedRequestKey !== requestKey;

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [query]);

  useEffect(() => {
    const controller = new AbortController();
    void getPaidMediaCatalog(debouncedQuery, page, controller.signal)
      .then((response) => {
        setError("");
        setItems(response.items);
        setTotal(response.pagination.count);
        setSelectedItems((current) => {
          if (current.size === 0) return current;
          const next = new Map(current);
          for (const item of response.items) {
            if (next.has(item.id)) next.set(item.id, item);
          }
          return next;
        });
      })
      .catch((reason: unknown) => {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setItems([]);
        setTotal(0);
        setError(userMessage(reason));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoadedRequestKey(requestKey);
      });
    return () => controller.abort();
  }, [debouncedQuery, page, requestKey]);

  const selectedList = useMemo(() => Array.from(selectedItems.values()), [selectedItems]);
  const totalPriceCents = useMemo(
    () => selectedList.reduce((sum, item) => sum + item.price_cents, 0),
    [selectedList],
  );
  const selectedOnPage = items.filter((item) => selectedItems.has(item.id)).length;
  const allOnPageSelected = items.length > 0 && selectedOnPage === items.length;

  const toggleItem = (item: PaidMediaCatalogItem, checked: boolean) => {
    if (
      checked &&
      !selectedItems.has(item.id) &&
      selectedItems.size >= PAID_MEDIA_SELECTION_LIMIT
    ) {
      messageApi.warning("每次最多选择 200 家媒体");
      return;
    }
    setSelectedItems((current) => {
      const next = new Map(current);
      if (checked) next.set(item.id, item);
      else next.delete(item.id);
      return next;
    });
    setSuccess("");
  };

  const toggleCurrentPage = (checked: boolean) => {
    setSelectedItems((current) => {
      const next = new Map(current);
      for (const item of items) {
        if (checked) {
          if (next.has(item.id) || next.size < PAID_MEDIA_SELECTION_LIMIT) next.set(item.id, item);
        } else {
          next.delete(item.id);
        }
      }
      return next;
    });
    if (
      checked &&
      selectedItems.size + items.filter((item) => !selectedItems.has(item.id)).length >
        PAID_MEDIA_SELECTION_LIMIT
    ) {
      messageApi.warning("每次最多选择 200 家媒体");
    }
    setSuccess("");
  };

  const submitInquiry = async () => {
    if (selectedItems.size === 0 || submitting) return;
    setSubmitting(true);
    setError("");
    try {
      await createPaidMediaInquiry(
        subjectId,
        Array.from(selectedItems.keys()),
        crypto.randomUUID(),
      );
      setConfirming(false);
      setSelectedItems(new Map());
      setSuccess("已提交给管理员，管理员将联系您确认发布安排。");
      messageApi.success("媒体发布需求已提交");
    } catch (reason) {
      setError(userMessage(reason));
      setConfirming(false);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <main className={styles.page}>
      {messageHolder}
      <section className={styles.header}>
        <div>
          <Text type="secondary">优化中心</Text>
          <Title level={2}>付费媒体</Title>
          <Paragraph type="secondary">搜索并勾选需要发布的媒体，系统会自动计算当前总价。</Paragraph>
        </div>
        <div className={styles.headerSummary}>
          <ShoppingCartOutlined aria-hidden="true" />
          <span>
            已选 {selectedItems.size} / {PAID_MEDIA_SELECTION_LIMIT} 家媒体
          </span>
        </div>
      </section>

      {error ? (
        <Alert type="warning" showIcon message={error} closable onClose={() => setError("")} />
      ) : null}
      {success ? (
        <Alert
          type="success"
          showIcon
          icon={<CheckCircleOutlined aria-hidden="true" />}
          message={success}
          closable
          onClose={() => setSuccess("")}
        />
      ) : null}

      <section className={styles.searchPanel} aria-label="付费媒体搜索">
        <Input
          value={query}
          prefix={<SearchOutlined aria-hidden="true" />}
          placeholder="搜索媒体名称或域名"
          aria-label="搜索媒体名称或域名"
          allowClear
          onChange={(event) => {
            setQuery(event.target.value);
            setPage(1);
          }}
        />
        <Text type="secondary" aria-live="polite">
          {debouncedQuery ? `找到 ${total} 家媒体` : `共 ${total} 家可选媒体`}
        </Text>
      </section>

      <section className={styles.selectionToolbar} aria-label="媒体选择操作">
        <Space wrap>
          <Checkbox
            checked={allOnPageSelected}
            indeterminate={selectedOnPage > 0 && !allOnPageSelected}
            disabled={items.length === 0 || loading}
            onChange={(event) => toggleCurrentPage(event.target.checked)}
          >
            全选本页
          </Checkbox>
          <Button
            type="link"
            disabled={selectedItems.size === 0}
            onClick={() => setSelectedItems(new Map())}
          >
            清空已选
          </Button>
        </Space>
        <Text type="secondary">
          已选 {selectedItems.size} / {PAID_MEDIA_SELECTION_LIMIT} 家，跨页选择会自动保留
        </Text>
      </section>

      {loading ? (
        <section className={styles.grid} aria-label="正在加载媒体列表">
          {Array.from({ length: 8 }, (_, index) => (
            <div className={styles.skeletonCard} key={index}>
              <Skeleton active avatar paragraph={{ rows: 2 }} title={{ width: "55%" }} />
            </div>
          ))}
        </section>
      ) : items.length > 0 ? (
        <section className={styles.grid} aria-label="付费媒体列表">
          {items.map((item) => {
            const selected = selectedItems.has(item.id);
            const externalUrl = getPaidMediaExternalUrl(item.url);
            return (
              <article
                className={[styles.mediaCard, selected && styles.mediaCardSelected]
                  .filter(Boolean)
                  .join(" ")}
                key={item.id}
              >
                <Checkbox
                  className={styles.cardCheckbox}
                  aria-label={`选择媒体：${item.name}`}
                  checked={selected}
                  onChange={(event) => toggleItem(item, event.target.checked)}
                />
                <span className={styles.logoWrap}>
                  <MediaLogo item={item} />
                </span>
                <span className={styles.cardBody}>
                  {externalUrl ? (
                    <a
                      className={styles.mediaName}
                      href={externalUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      aria-label={`打开 ${item.name} 参考链接`}
                    >
                      {item.name}
                      <ExportOutlined aria-hidden="true" />
                    </a>
                  ) : (
                    <Text className={styles.mediaName} strong>
                      {item.name}
                    </Text>
                  )}
                  <Text className={styles.domain} type="secondary" title={item.domain ?? undefined}>
                    {item.domain || "暂无可用链接"}
                  </Text>
                  <Text className={styles.price} strong>
                    {formatPrice(item.price_cents)}
                  </Text>
                  <Text className={styles.priceCaption} type="secondary">
                    参考发布价
                  </Text>
                </span>
              </article>
            );
          })}
        </section>
      ) : (
        <section className={styles.emptyState}>
          <Empty description="未找到匹配的媒体，请更换名称或域名后再试" />
        </section>
      )}

      {total > PAID_MEDIA_PAGE_SIZE ? (
        <div className={styles.pagination}>
          <Pagination
            aria-label="付费媒体分页"
            current={page}
            pageSize={PAID_MEDIA_PAGE_SIZE}
            total={total}
            showSizeChanger={false}
            showTotal={(count) => `共 ${count} 家媒体`}
            disabled={loading}
            onChange={setPage}
          />
        </div>
      ) : null}

      <aside className={styles.calculator} aria-label="价格计算器">
        <span className={styles.calculatorIcon} aria-hidden="true">
          <ShoppingCartOutlined />
        </span>
        <span className={styles.calculatorSummary}>
          <Text type="secondary">
            价格计算器 · 已选 {selectedItems.size} / {PAID_MEDIA_SELECTION_LIMIT} 家
          </Text>
          <strong>{formatPrice(totalPriceCents)}</strong>
        </span>
        <Button
          type="primary"
          size="large"
          disabled={selectedItems.size === 0}
          onClick={() => setConfirming(true)}
        >
          提交发布需求
        </Button>
      </aside>

      <Modal
        open={confirming}
        title="确认提交媒体发布需求"
        okText="确认联系管理员提交"
        cancelText="取消提交"
        confirmLoading={submitting}
        mask={{ closable: !submitting }}
        keyboard={!submitting}
        onOk={() => void submitInquiry()}
        onCancel={() => {
          if (!submitting) setConfirming(false);
        }}
      >
        <Space orientation="vertical" size="middle" style={{ width: "100%" }}>
          <Paragraph>
            您已选择 <strong>{selectedItems.size}</strong> 家媒体，当前合计为　
            <strong>{formatPrice(totalPriceCents)}</strong>。
          </Paragraph>
          <Alert
            type="info"
            showIcon
            message="提交后不会立即扣款"
            description="管理员会联系您确认媒体档期、发布安排和最终费用。"
          />
        </Space>
      </Modal>
    </main>
  );
}
