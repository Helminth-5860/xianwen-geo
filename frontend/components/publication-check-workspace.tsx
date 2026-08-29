"use client";

import {
  ApiOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  CloseCircleFilled,
  DeleteOutlined,
  ExclamationCircleFilled,
  ExportOutlined,
  GlobalOutlined,
  LinkOutlined,
  RadarChartOutlined,
  SafetyCertificateOutlined,
  ThunderboltOutlined,
} from "@ant-design/icons";
import { Button, Checkbox, Input, Modal, Pagination, Spin, Tag, Tooltip } from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { userMessage } from "@/lib/auth-client";
import {
  bulkDeletePublicationVerifications,
  deletePublicationVerification,
  getPublicationVerifications,
  verifyPublicationUrl,
  type PublicationVerificationCheck,
  type PublicationVerificationStats,
  type PublicationVerificationStatus,
} from "@/lib/publication-verification-client";

import styles from "./publication-check-workspace.module.css";

type Props = Readonly<{ subjectId: string }>;
type HistoryFilter = PublicationVerificationStatus | "all";

const EMPTY_STATS: PublicationVerificationStats = {
  total: 0,
  published: 0,
  failed: 0,
  unknown: 0,
  success_rate: 0,
};

const statusPresentation = {
  published: {
    label: "发布成功",
    english: "PUBLICLY AVAILABLE",
    icon: <CheckCircleFilled />,
    tone: "success",
  },
  failed: {
    label: "发布失败",
    english: "NOT AVAILABLE",
    icon: <CloseCircleFilled />,
    tone: "danger",
  },
  unknown: {
    label: "暂时无法确认",
    english: "NEEDS CONFIRMATION",
    icon: <ExclamationCircleFilled />,
    tone: "warning",
  },
} as const;

function AnimatedNumber({
  value,
  decimals = 0,
  suffix = "",
}: Readonly<{ value: number; decimals?: number; suffix?: string }>) {
  const [display, setDisplay] = useState(0);
  const previous = useRef(0);

  useEffect(() => {
    const from = previous.current;
    const startedAt = performance.now();
    let frame = 0;
    const tick = (now: number) => {
      const progress = Math.min(1, (now - startedAt) / 650);
      const eased = 1 - Math.pow(1 - progress, 3);
      setDisplay(from + (value - from) * eased);
      if (progress < 1) frame = requestAnimationFrame(tick);
      else previous.current = value;
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [value]);

  return (
    <span className={styles.tabularNumber}>
      {display.toFixed(decimals)}
      {suffix}
    </span>
  );
}

function formatCheckedAt(value: string) {
  const date = new Date(value);
  const today = new Date();
  const sameDay = date.toDateString() === today.toDateString();
  return sameDay
    ? `今天 ${date.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit" })}`
    : date.toLocaleString("zh-CN", {
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
}

function identifySite(rawUrl: string) {
  try {
    const hostname = new URL(rawUrl).hostname.toLowerCase().replace(/^www\./, "");
    const known: Array<[string, string]> = [
      ["mp.weixin.qq.com", "微信公众号"],
      ["zhihu.com", "知乎"],
      ["baijiahao.baidu.com", "百家号"],
      ["sohu.com", "搜狐"],
      ["163.com", "网易"],
      ["qq.com", "腾讯"],
      ["toutiao.com", "今日头条"],
      ["weibo.com", "微博"],
    ];
    const matched = known.find(
      ([domain]) => hostname === domain || hostname.endsWith(`.${domain}`),
    );
    return { hostname, label: matched?.[1] ?? "公开网页" };
  } catch {
    return { hostname: "", label: "公开网页" };
  }
}

function chainState(
  item: PublicationVerificationCheck | undefined,
  checking: boolean,
  scanStage: number,
  step: number,
) {
  if (checking) return scanStage > step ? "passed" : scanStage === step ? "active" : "waiting";
  if (!item) return "waiting";
  if (item.status === "published") return "passed";
  if (step === 0) return item.http_status ? "passed" : "failed";
  if (step === 1) {
    if (!item.http_status) return "waiting";
    return item.http_status >= 200 && item.http_status < 300 ? "passed" : "failed";
  }
  return item.status === "published" ? "passed" : "failed";
}

export function PublicationCheckWorkspace({ subjectId }: Props) {
  const [url, setUrl] = useState("");
  const [result, setResult] = useState<PublicationVerificationCheck>();
  const [items, setItems] = useState<PublicationVerificationCheck[]>([]);
  const [stats, setStats] = useState<PublicationVerificationStats>(EMPTY_STATS);
  const [checking, setChecking] = useState(false);
  const [scanStage, setScanStage] = useState(0);
  const [loading, setLoading] = useState(true);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState<HistoryFilter>("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  const [historyCount, setHistoryCount] = useState(0);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);

  const loadHistory = useCallback(
    async (targetPage: number, targetFilter: HistoryFilter, targetPageSize = pageSize) => {
      setHistoryLoading(true);
      try {
        const data = await getPublicationVerifications(
          subjectId,
          targetPage,
          targetPageSize,
          targetFilter,
        );
        setItems(data.items);
        setStats(data.stats);
        setHistoryCount(data.pagination.count);
        setSelectedIds([]);
      } catch (reason) {
        setError(userMessage(reason));
      } finally {
        setLoading(false);
        setHistoryLoading(false);
      }
    },
    [pageSize, subjectId],
  );

  useEffect(() => {
    void loadHistory(page, filter, pageSize);
  }, [filter, loadHistory, page, pageSize]);

  useEffect(() => {
    if (!checking) return;
    setScanStage(0);
    const first = window.setTimeout(() => setScanStage(1), 260);
    const second = window.setTimeout(() => setScanStage(2), 680);
    return () => {
      window.clearTimeout(first);
      window.clearTimeout(second);
    };
  }, [checking]);

  const site = useMemo(() => identifySite(url.trim()), [url]);
  const allCurrentSelected =
    items.length > 0 && items.every((item) => selectedIds.includes(item.id));

  const submit = async () => {
    const value = url.trim();
    if (!value) return;
    try {
      const parsed = new URL(value);
      if (!["http:", "https:"].includes(parsed.protocol)) throw new Error();
    } catch {
      setError("请输入完整的公开文章链接，例如 https://example.com/article。");
      return;
    }

    setChecking(true);
    setResult(undefined);
    setError("");
    try {
      const created = await verifyPublicationUrl(subjectId, value);
      setResult(created);
      setScanStage(3);
      setFilter("all");
      setPage(1);
      await loadHistory(1, "all", pageSize);
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setChecking(false);
    }
  };

  const toggleSelection = (id: string, checked: boolean) => {
    setSelectedIds((current) =>
      checked ? [...new Set([...current, id])] : current.filter((item) => item !== id),
    );
  };

  const toggleCurrentPage = (checked: boolean) => {
    setSelectedIds(checked ? items.map((item) => item.id) : []);
  };

  const confirmDelete = (ids: string[]) => {
    if (!ids.length) return;
    Modal.confirm({
      title: `删除 ${ids.length} 条检测记录？`,
      content: "仅删除显问中的检测历史，不会影响第三方网站上的文章。",
      okText: "确认删除",
      cancelText: "取消",
      okButtonProps: { danger: true },
      async onOk() {
        if (ids.length === 1) {
          await deletePublicationVerification(subjectId, ids[0]);
        } else {
          await bulkDeletePublicationVerifications(subjectId, ids);
        }
        if (result && ids.includes(result.id)) setResult(undefined);
        const nextPage = items.length === ids.length && page > 1 ? page - 1 : page;
        setPage(nextPage);
        await loadHistory(nextPage, filter, pageSize);
      },
    });
  };

  const filterItems: Array<{ value: HistoryFilter; label: string }> = [
    { value: "all", label: "全部" },
    { value: "published", label: "发布成功" },
    { value: "failed", label: "发布失败" },
    { value: "unknown", label: "无法确认" },
  ];

  const currentPresentation = result ? statusPresentation[result.status] : undefined;
  const successDegrees = Math.max(0, Math.min(360, stats.success_rate * 3.6));

  return (
    <main className={styles.page}>
      <div className={styles.backgroundGrid} aria-hidden="true" />
      <div className={styles.backgroundGlow} aria-hidden="true" />

      <section className={styles.hero}>
        <div className={styles.heroHeading}>
          <span className={styles.eyebrow}>
            <SafetyCertificateOutlined /> PUBLICATION VERIFICATION
          </span>
          <h1>发布检测</h1>
          <p>检测互联网任意公开文章是否已成功上线并可正常访问。</p>
        </div>

        <div className={`${styles.scanner} ${checking ? styles.scannerActive : ""}`}>
          <div className={styles.scannerAccent} aria-hidden="true" />
          {checking && <div className={styles.scanBeam} aria-hidden="true" />}
          <div className={styles.urlIdentity}>
            <span className={styles.urlIcon}>
              <LinkOutlined />
            </span>
            <div>
              <strong>{site.hostname || "粘贴任意公开文章链接"}</strong>
              <small>{site.hostname ? site.label : "无需由显问生成，支持互联网公开页面"}</small>
            </div>
          </div>
          <div className={styles.inputRow}>
            <Input
              aria-label="公开文章链接"
              value={url}
              disabled={checking}
              placeholder="https://example.com/article/..."
              onChange={(event) => {
                setUrl(event.target.value);
                setError("");
              }}
              onPressEnter={() => void submit()}
              prefix={<GlobalOutlined />}
            />
            <Button
              type="primary"
              size="large"
              loading={checking}
              disabled={!url.trim() || checking}
              icon={<RadarChartOutlined />}
              onClick={() => void submit()}
            >
              {checking ? "正在检测" : "立即检测"}
            </Button>
          </div>

          <div className={styles.verificationChain}>
            {[
              ["连接站点", "验证目标地址是否可访问"],
              ["验证页面", "检查 HTTP 与公开访问状态"],
              ["识别内容", "确认页面存在有效文章内容"],
            ].map(([title, description], index) => {
              const state = chainState(result, checking, scanStage, index);
              return (
                <div key={title} className={`${styles.chainStep} ${styles[`chain_${state}`]}`}>
                  <span className={styles.chainNode}>
                    {state === "passed" ? <CheckCircleFilled /> : index + 1}
                  </span>
                  <div>
                    <strong>{title}</strong>
                    <small>{description}</small>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {error && <div className={styles.errorBanner}>{error}</div>}
      </section>

      <section className={styles.resultAndRate}>
        <div
          className={`${styles.resultCard} ${
            result ? styles[`result_${statusPresentation[result.status].tone}`] : styles.resultIdle
          }`}
        >
          {result && currentPresentation ? (
            <>
              <div className={styles.resultIcon}>{currentPresentation.icon}</div>
              <div className={styles.resultMain}>
                <span className={styles.resultEnglish}>{currentPresentation.english}</span>
                <h2>{currentPresentation.label}</h2>
                <p>{result.result_message}</p>
                <div className={styles.resultTitle}>
                  <span>识别标题</span>
                  <strong>{result.page_title || "未识别到页面标题"}</strong>
                </div>
              </div>
              <div className={styles.resultMeta}>
                <div><span>网站</span><strong>{result.hostname || "—"}</strong></div>
                <div><span>HTTP</span><strong>{result.http_status ?? "—"}</strong></div>
                <div><span>响应时间</span><strong>{result.response_time_ms ?? "—"} ms</strong></div>
                <div><span>检测时间</span><strong>{formatCheckedAt(result.checked_at)}</strong></div>
              </div>
              <a
                className={styles.openLink}
                href={result.final_url || result.requested_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                打开原链接 <ExportOutlined />
              </a>
            </>
          ) : (
            <div className={styles.idleResult}>
              <span className={styles.idleIcon}><ApiOutlined /></span>
              <div>
                <span>VERIFICATION RESULT</span>
                <h2>{checking ? "正在验证公开发布状态" : "等待检测"}</h2>
                <p>
                  {checking
                    ? "系统正在连接目标站点并验证页面状态。"
                    : "粘贴文章公开链接并开始检测，结果会显示在这里。"}
                </p>
              </div>
            </div>
          )}
        </div>

        <div className={styles.rateCard}>
          <div className={styles.rateHeader}>
            <span>PUBLICATION HEALTH</span>
            <strong>发布成功率</strong>
          </div>
          <div
            className={styles.rateRing}
            style={{
              background: `conic-gradient(#35b88a ${successDegrees}deg, #e8eef7 ${successDegrees}deg 360deg)`,
            }}
          >
            <div>
              <strong><AnimatedNumber value={stats.success_rate} decimals={1} suffix="%" /></strong>
              <span>成功率</span>
            </div>
          </div>
          <p>基于当前主体保留的检测历史计算。</p>
        </div>
      </section>

      <section className={styles.statsGrid}>
        <div className={styles.statCard}>
          <span className={styles.statIcon}><RadarChartOutlined /></span>
          <div><small>累计检测</small><strong><AnimatedNumber value={stats.total} /></strong></div>
        </div>
        <div className={`${styles.statCard} ${styles.statSuccess}`}>
          <span className={styles.statIcon}><CheckCircleFilled /></span>
          <div><small>发布成功</small><strong><AnimatedNumber value={stats.published} /></strong></div>
        </div>
        <div className={`${styles.statCard} ${styles.statDanger}`}>
          <span className={styles.statIcon}><CloseCircleFilled /></span>
          <div><small>发布失败</small><strong><AnimatedNumber value={stats.failed} /></strong></div>
        </div>
        <div className={`${styles.statCard} ${styles.statWarning}`}>
          <span className={styles.statIcon}><ExclamationCircleFilled /></span>
          <div><small>无法确认</small><strong><AnimatedNumber value={stats.unknown} /></strong></div>
        </div>
      </section>

      <section className={styles.historyPanel}>
        <div className={styles.historyHeader}>
          <div>
            <span className={styles.eyebrow}>VERIFICATION HISTORY</span>
            <h2>最近检测记录</h2>
            <p>保留需要的检测结果，不需要的记录可随时删除。</p>
          </div>
          <div className={styles.historyActions}>
            {selectedIds.length > 0 && (
              <span className={styles.selectedCount}>已选择 {selectedIds.length} 条</span>
            )}
            <Button
              danger
              icon={<DeleteOutlined />}
              disabled={!selectedIds.length}
              onClick={() => confirmDelete(selectedIds)}
            >
              删除已选
            </Button>
          </div>
        </div>

        <div className={styles.historyToolbar}>
          <div className={styles.filters}>
            {filterItems.map((item) => (
              <button
                key={item.value}
                type="button"
                className={filter === item.value ? styles.filterActive : ""}
                onClick={() => {
                  setPage(1);
                  setFilter(item.value);
                }}
              >
                {item.label}
              </button>
            ))}
          </div>
          <span>共 {historyCount} 条</span>
        </div>

        {loading ? (
          <div className={styles.loadingState}><Spin description="正在加载检测记录" /></div>
        ) : items.length ? (
          <div className={`${styles.historyTable} ${historyLoading ? styles.historyRefreshing : ""}`}>
            <div className={styles.tableHeader}>
              <Checkbox
                checked={allCurrentSelected}
                indeterminate={selectedIds.length > 0 && !allCurrentSelected}
                onChange={(event) => toggleCurrentPage(event.target.checked)}
              />
              <span>状态</span>
              <span>页面信息</span>
              <span>网站</span>
              <span>检测结果</span>
              <span>时间</span>
              <span>操作</span>
            </div>
            {items.map((item) => {
              const presentation = statusPresentation[item.status];
              return (
                <div className={styles.historyRow} key={item.id}>
                  <Checkbox
                    checked={selectedIds.includes(item.id)}
                    onChange={(event) => toggleSelection(item.id, event.target.checked)}
                  />
                  <Tag className={`${styles.statusTag} ${styles[`tag_${presentation.tone}`]}`}>
                    {presentation.icon} {presentation.label}
                  </Tag>
                  <div className={styles.pageInfo}>
                    <strong>{item.page_title || "公开文章"}</strong>
                    <Tooltip title={item.final_url || item.requested_url}>
                      <span>{item.final_url || item.requested_url}</span>
                    </Tooltip>
                  </div>
                  <div className={styles.hostCell}>
                    <GlobalOutlined />
                    <span>{item.hostname || "—"}</span>
                  </div>
                  <div className={styles.resultCell}>
                    <strong>{item.http_status ? `HTTP ${item.http_status}` : "—"}</strong>
                    <small>
                      {item.response_time_ms !== null
                        ? `${item.response_time_ms} ms`
                        : item.result_message}
                    </small>
                  </div>
                  <div className={styles.timeCell}>
                    <ClockCircleOutlined />
                    <span>{formatCheckedAt(item.checked_at)}</span>
                  </div>
                  <div className={styles.rowActions}>
                    <Tooltip title="打开原链接">
                      <a
                        href={item.final_url || item.requested_url}
                        target="_blank"
                        rel="noopener noreferrer"
                      >
                        <ExportOutlined />
                      </a>
                    </Tooltip>
                    <Tooltip title="删除记录">
                      <button type="button" onClick={() => confirmDelete([item.id])}>
                        <DeleteOutlined />
                      </button>
                    </Tooltip>
                  </div>
                </div>
              );
            })}
          </div>
        ) : (
          <div className={styles.emptyState}>
            <span className={styles.emptyIcon}><ThunderboltOutlined /></span>
            <h3>{filter === "all" ? "还没有发布检测记录" : "当前筛选下没有记录"}</h3>
            <p>
              {filter === "all"
                ? "在上方粘贴互联网任意公开文章链接即可开始检测。"
                : "切换其他状态，或开始一次新的发布检测。"}
            </p>
          </div>
        )}

        {historyCount > 0 && (
          <div className={styles.pagination}>
            <Pagination
              current={page}
              pageSize={pageSize}
              total={historyCount}
              showSizeChanger
              pageSizeOptions={[10, 20, 50]}
              showTotal={(total) => `共 ${total} 条`}
              onChange={(nextPage, nextSize) => {
                if (nextSize !== pageSize) {
                  setPageSize(nextSize);
                  setPage(1);
                } else {
                  setPage(nextPage);
                }
              }}
            />
          </div>
        )}
      </section>
    </main>
  );
}
