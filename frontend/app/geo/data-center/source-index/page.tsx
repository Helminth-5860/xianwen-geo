"use client";

import { ExportOutlined, InfoCircleOutlined, ReloadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Pagination,
  Progress,
  Row,
  Select,
  Skeleton,
  Space,
  Spin,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  type TableProps,
} from "antd";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getSourceIndexItems,
  getSourceIndexScan,
  getSourceIndexState,
  startSourceIndexScan,
  type QueryCoverage,
  type SourceIndexItem,
  type SourceIndexOrdering,
  type SourceIndexScanDetail,
  type SourceIndexScanSummary,
  type SourceIndexState,
  type SourceType,
  type TopSource,
} from "@/lib/source-index-client";

import styles from "./source-index.module.css";

const { Paragraph, Text, Title } = Typography;
const PAGE_SIZE = 20;

const SOURCE_TYPE_LABELS: Record<SourceType, string> = {
  government_association: "政府/协会",
  news_media: "新闻媒体",
  industry_media: "行业媒体",
  enterprise_site: "企业网站",
  content_platform: "内容平台/自媒体",
  directory_business: "黄页/工商",
  forum_community: "论坛社区",
  other: "其他",
};

const SOURCE_TYPE_COLORS: Partial<Record<SourceType, string>> = {
  government_association: "purple",
  news_media: "blue",
  industry_media: "cyan",
  enterprise_site: "green",
  content_platform: "geekblue",
  directory_business: "default",
  forum_community: "gold",
};

const STAGE_LABELS: Record<SourceIndexScanSummary["stage"], string> = {
  preparing: "正在准备主体信息",
  searching: "正在扫描公开网络",
  classifying: "正在去重与识别来源",
  scoring: "正在计算信源权重",
  completed: "扫描已完成",
};

const FACTOR_LABELS = {
  exposure: "曝光规模",
  diversity: "独立来源",
  authority: "来源权威",
  visibility: "搜索可见度",
  freshness: "内容新鲜度",
} as const;

function sourceTypeLabel(value: SourceType) {
  return SOURCE_TYPE_LABELS[value] ?? value;
}

function formatDate(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

function formatDateTime(value: string | null) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

function formatElapsed(seconds: number | null) {
  if (seconds === null) return "—";
  if (seconds < 60) return `${Math.max(1, Math.round(seconds))} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = Math.round(seconds % 60);
  return `${minutes} 分 ${rest} 秒`;
}

function stableErrorMessage(code: string) {
  const messages: Record<string, string> = {
    BAIDU_SEARCH_API_KEY_MISSING: "百度公开搜索尚未配置，请联系管理员完成搜索服务配置。",
    BAIDU_SEARCH_AUTH_FAILED: "百度公开搜索认证失败，请检查搜索服务配置。",
    BAIDU_SEARCH_RATE_LIMITED: "百度公开搜索请求过于频繁，请稍后重新扫描。",
    BAIDU_SEARCH_NETWORK_ERROR: "公开搜索网络暂时不可用，请稍后重试。",
    BAIDU_SEARCH_UPSTREAM_ERROR: "百度公开搜索暂时不可用，请稍后重试。",
    BAIDU_SEARCH_NO_USABLE_RESULTS: "本次公开搜索未取得可用结果，请稍后重试。",
    SOURCE_INDEX_SUBJECT_IDENTITY_MISSING: "当前主体缺少可用于公开搜索的企业名称或品牌名称。",
    SOURCE_INDEX_TIMEOUT: "上一次扫描异常中断，请重新发起扫描。",
  };
  return messages[code] ?? "信源扫描未完成，请稍后重新扫描。";
}

function statusNotice(result: SourceIndexScanDetail) {
  if (result.status === "limit_reached") {
    return (
      <Alert
        type="info"
        showIcon
        message="本次扫描已达到最大检索边界"
        description="系统已基于当前发现的公开信源完成分析。达到时间或请求上限不代表扫描失败。"
      />
    );
  }
  if (result.status === "partial") {
    return (
      <Alert
        type="warning"
        showIcon
        message="部分搜索请求未完成"
        description="本次结果仍可使用，但公开信源覆盖可能低于正常扫描。"
      />
    );
  }
  return null;
}

export default function SourceIndexPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();
  const subjectId = subject?.id ?? "";
  const [state, setState] = useState<SourceIndexState | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [sourceType, setSourceType] = useState<SourceType | "all">("all");
  const [ordering, setOrdering] = useState<SourceIndexOrdering>("-source_weight");
  const [items, setItems] = useState<SourceIndexItem[]>([]);
  const [itemCount, setItemCount] = useState(0);
  const [itemsLoading, setItemsLoading] = useState(false);

  const loadState = useCallback(async (targetSubjectId: string) => {
    const result = await getSourceIndexState(targetSubjectId);
    setState(result);
    return result;
  }, []);

  useEffect(() => {
    if (subjectLoading || !subjectId) return;
    let current = true;
    const fetchState = async () => {
      await Promise.resolve();
      if (!current) return;
      setLoading(true);
      setError("");
      try {
        const result = await getSourceIndexState(subjectId);
        if (current) setState(result);
      } catch (reason: unknown) {
        if (current) setError(userMessage(reason));
      } finally {
        if (current) setLoading(false);
      }
    };
    void fetchState();
    return () => {
      current = false;
    };
  }, [subjectId, subjectLoading]);

  const activeScan = state?.active_scan ?? null;
  const latestResult = state?.latest_result ?? null;

  useEffect(() => {
    if (!subjectId || !activeScan?.id) return;
    let cancelled = false;
    let timer = 0;

    const poll = async () => {
      try {
        const scan = await getSourceIndexScan(activeScan.id);
        if (cancelled) return;
        if (["queued", "running"].includes(scan.status)) {
          setState((current) => (current ? { ...current, active_scan: scan } : current));
          timer = window.setTimeout(() => void poll(), 1800);
          return;
        }
        const refreshed = await loadState(subjectId);
        if (!cancelled && scan.status === "failed") {
          setError(stableErrorMessage(scan.stable_error_code));
        } else if (!cancelled && refreshed.latest_result) {
          setError("");
          setPage(1);
        }
      } catch (reason: unknown) {
        if (!cancelled) {
          setError(userMessage(reason));
          timer = window.setTimeout(() => void poll(), 3000);
        }
      }
    };

    timer = window.setTimeout(() => void poll(), 900);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [activeScan?.id, loadState, subjectId]);

  useEffect(() => {
    if (!latestResult?.id) return;
    let current = true;
    const fetchItems = async () => {
      await Promise.resolve();
      if (!current) return;
      setItemsLoading(true);
      try {
        const result = await getSourceIndexItems(latestResult.id, {
          page,
          pageSize: PAGE_SIZE,
          sourceType: sourceType === "all" ? undefined : sourceType,
          ordering,
        });
        if (!current) return;
        setItems(result.results);
        setItemCount(result.count);
      } catch (reason: unknown) {
        if (current) setError(userMessage(reason));
      } finally {
        if (current) setItemsLoading(false);
      }
    };
    void fetchItems();
    return () => {
      current = false;
    };
  }, [latestResult?.id, ordering, page, sourceType]);

  const startScan = async () => {
    if (!subjectId || activeScan || starting) return;
    setStarting(true);
    setError("");
    try {
      const scan = await startSourceIndexScan(subjectId);
      setState((current) => ({
        active_scan: scan,
        latest_result: current?.latest_result ?? null,
      }));
    } catch (reason: unknown) {
      setError(userMessage(reason));
    } finally {
      setStarting(false);
    }
  };

  const distributionTotal =
    latestResult?.source_type_distribution.reduce((sum, row) => sum + row.count, 0) ?? 0;

  const columns: TableProps<SourceIndexItem>["columns"] = useMemo(
    () => [
      {
        title: "来源",
        key: "source",
        width: 170,
        render: (_, item) => (
          <Space direction="vertical" size={2}>
            <Text strong>{item.website || item.root_domain}</Text>
            <Text type="secondary" ellipsis={{ tooltip: item.root_domain }}>
              {item.root_domain}
            </Text>
          </Space>
        ),
      },
      {
        title: "标题",
        dataIndex: "title",
        key: "title",
        width: 420,
        render: (title: string, item) => (
          <Space direction="vertical" size={4} className={styles.titleCell}>
            <a href={item.original_url} target="_blank" rel="noopener noreferrer">
              {title} <ExportOutlined aria-hidden="true" />
            </a>
            {item.snippet ? (
              <Text type="secondary" ellipsis={{ tooltip: item.snippet }}>
                {item.snippet}
              </Text>
            ) : null}
          </Space>
        ),
      },
      {
        title: "类型",
        dataIndex: "source_type",
        key: "source_type",
        width: 130,
        render: (value: SourceType) => (
          <Tag color={SOURCE_TYPE_COLORS[value]}>{sourceTypeLabel(value)}</Tag>
        ),
      },
      {
        title: "发布时间",
        dataIndex: "published_at",
        key: "published_at",
        width: 120,
        render: (value: string | null) => formatDate(value),
      },
      {
        title: "本次最好位置",
        dataIndex: "best_rank",
        key: "best_rank",
        width: 120,
        render: (value: number) => (value > 50 ? "50+" : `#${value}`),
      },
      {
        title: (
          <Space size={4}>
            信源权重
            <Tooltip title="由来源权威度、主体相关度、搜索可见度和新鲜度确定性计算，不是 AI 主观评分。">
              <InfoCircleOutlined />
            </Tooltip>
          </Space>
        ),
        dataIndex: "source_weight",
        key: "source_weight",
        width: 120,
        render: (value: string, item) => (
          <Tooltip
            title={`权威 ${item.authority_score} · 相关 ${item.relevance_score} · 可见 ${item.visibility_score} · 新鲜 ${item.freshness_score}`}
          >
            <Tag color={Number(value) >= 75 ? "blue" : undefined}>{Number(value).toFixed(1)}</Tag>
          </Tooltip>
        ),
      },
    ],
    [],
  );

  if (subjectLoading) return <Spin fullscreen description="正在加载信源指数" />;

  return (
    <main className={styles.page}>
      <section className={styles.header}>
        <div>
          <Text type="secondary">公开信源发现</Text>
          <Title level={2}>信源指数</Title>
          <Paragraph type="secondary">
            扫描当前主体在公开网络中可被搜索发现的信源，分析曝光规模、独立来源、媒体覆盖与信源权重。
          </Paragraph>
        </div>
        <Space wrap>
          {latestResult ? (
            <Text type="secondary">最近扫描 {formatDateTime(latestResult.finished_at)}</Text>
          ) : null}
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            loading={starting}
            disabled={!subject || Boolean(activeScan)}
            onClick={() => void startScan()}
          >
            {activeScan ? "正在扫描" : latestResult ? "更新信源" : "开始扫描"}
          </Button>
        </Space>
      </section>

      {!subject ? (
        <Card>
          <Empty description="请先绑定主体">
            <Button type="primary" href="/subjects">
              进入主体档案
            </Button>
          </Empty>
        </Card>
      ) : (
        <>
          <section className="geo-dashboard__subject-bar">
            <div>
              <Text type="secondary">当前主体</Text>
              <Title level={3}>{subject.official_name || subject.subject_type.name}</Title>
            </div>
            <Tag>百度公开搜索 · 元数据扫描</Tag>
          </section>

          {error ? <Alert type="error" showIcon message={error} /> : null}

          {activeScan ? (
            <Card className={styles.scanCard}>
              <div className={styles.scanStatus}>
                <Spin size="small" />
                <div>
                  <Text strong>{STAGE_LABELS[activeScan.stage]}</Text>
                  <Paragraph type="secondary">
                    扫描会在新增信源趋于饱和时自动结束；极端情况下最迟 5 分钟收口。
                  </Paragraph>
                </div>
              </div>
              <div className={styles.liveMetrics} aria-live="polite">
                <span>
                  <Text type="secondary">原始结果</Text>
                  <strong>{activeScan.progress.raw ?? activeScan.raw_result_count}</strong>
                </span>
                <span>
                  <Text type="secondary">去重后</Text>
                  <strong>{activeScan.progress.unique ?? activeScan.unique_result_count}</strong>
                </span>
                <span>
                  <Text type="secondary">搜索请求</Text>
                  <strong>{activeScan.provider_request_count}</strong>
                </span>
                <span>
                  <Text type="secondary">计划查询</Text>
                  <strong>{activeScan.progress.queries_planned ?? activeScan.query_count}</strong>
                </span>
              </div>
            </Card>
          ) : null}

          {loading ? (
            <Card>
              <Skeleton active paragraph={{ rows: 5 }} />
            </Card>
          ) : !latestResult ? (
            <Card className="geo-dashboard__empty">
              <Empty
                description={
                  <span>
                    当前主体还没有公开信源扫描结果。
                    <br />
                    系统只读取搜索结果标题、链接、摘要、来源和时间，不抓取网页全文。
                  </span>
                }
              >
                <Button type="primary" loading={starting} onClick={() => void startScan()}>
                  开始首次扫描
                </Button>
              </Empty>
            </Card>
          ) : (
            <>
              {statusNotice(latestResult)}

              <section className={styles.kpiGrid} aria-label="信源核心指标">
                <Card>
                  <Statistic
                    title="信源指数"
                    value={Number(latestResult.index_score ?? 0)}
                    precision={1}
                  />
                </Card>
                <Card>
                  <Statistic title="公开信源" value={latestResult.public_source_count} />
                </Card>
                <Card>
                  <Statistic title="独立来源" value={latestResult.independent_domain_count} />
                </Card>
                <Card>
                  <Statistic title="新闻 / 媒体" value={latestResult.news_media_count} />
                </Card>
                <Card>
                  <Statistic title="高权重信源" value={latestResult.high_weight_count} />
                </Card>
                <Card>
                  <Statistic title="近30天信源" value={latestResult.recent_30d_count} />
                </Card>
              </section>

              <section className={styles.analysisGrid}>
                <Card title="指数构成" className={styles.sectionCard}>
                  <div className={styles.factorList}>
                    {Object.entries(FACTOR_LABELS).map(([key, label]) => {
                      const score =
                        latestResult.factor_scores[key as keyof typeof FACTOR_LABELS] ?? 0;
                      return (
                        <div className={styles.factorRow} key={key}>
                          <span>{label}</span>
                          <Progress percent={Math.round(score)} size="small" />
                        </div>
                      );
                    })}
                  </div>
                  <Text type="secondary">
                    最终指数由固定公式计算，数量采用饱和处理，避免大量低价值转载直接刷高指数。
                  </Text>
                </Card>

                <Card title="来源类型分布" className={styles.sectionCard}>
                  <div className={styles.distributionList}>
                    {latestResult.source_type_distribution.map((row) => {
                      const percent = distributionTotal
                        ? Math.round((row.count / distributionTotal) * 100)
                        : 0;
                      return (
                        <div className={styles.distributionRow} key={row.source_type}>
                          <span>
                            <Tag color={SOURCE_TYPE_COLORS[row.source_type]}>
                              {sourceTypeLabel(row.source_type)}
                            </Tag>
                            <Text>{row.count}</Text>
                          </span>
                          <Progress percent={percent} showInfo={false} size="small" />
                        </div>
                      );
                    })}
                  </div>
                </Card>
              </section>

              <Card title="关键词曝光" className={styles.sectionCard}>
                <Table<QueryCoverage>
                  rowKey="query"
                  size="small"
                  pagination={false}
                  dataSource={latestResult.query_coverage.slice(0, 12)}
                  columns={[
                    { title: "查询主题", dataIndex: "query", key: "query" },
                    {
                      title: "发现信源",
                      dataIndex: "source_count",
                      key: "source_count",
                      width: 120,
                    },
                    {
                      title: "独立来源",
                      dataIndex: "independent_source_count",
                      key: "independent_source_count",
                      width: 120,
                    },
                    {
                      title: "本次最好位置",
                      dataIndex: "best_rank",
                      key: "best_rank",
                      width: 140,
                      render: (value: number | null) => (value ? `#${value}` : "—"),
                    },
                  ]}
                />
              </Card>

              <Card title="重点来源" className={styles.sectionCard}>
                <Table<TopSource>
                  rowKey={(row) => `${row.root_domain}:${row.source_type}`}
                  size="small"
                  pagination={false}
                  dataSource={latestResult.top_sources.slice(0, 12)}
                  columns={[
                    { title: "来源域名", dataIndex: "root_domain", key: "root_domain" },
                    {
                      title: "类型",
                      dataIndex: "source_type",
                      key: "source_type",
                      width: 150,
                      render: (value: SourceType) => (
                        <Tag color={SOURCE_TYPE_COLORS[value]}>{sourceTypeLabel(value)}</Tag>
                      ),
                    },
                    {
                      title: "信源数",
                      dataIndex: "source_count",
                      key: "source_count",
                      width: 100,
                    },
                    {
                      title: "平均权重",
                      dataIndex: "average_weight",
                      key: "average_weight",
                      width: 110,
                      render: (value: number) => value.toFixed(1),
                    },
                    {
                      title: "最高权重",
                      dataIndex: "highest_weight",
                      key: "highest_weight",
                      width: 110,
                      render: (value: number) => value.toFixed(1),
                    },
                  ]}
                />
              </Card>

              <Card
                title="信源明细"
                className={styles.sectionCard}
                extra={
                  <Space wrap>
                    <Select
                      aria-label="信源类型筛选"
                      value={sourceType}
                      style={{ width: 170 }}
                      options={[
                        { value: "all", label: "全部来源" },
                        ...Object.entries(SOURCE_TYPE_LABELS).map(([value, label]) => ({
                          value,
                          label,
                        })),
                      ]}
                      onChange={(value) => {
                        setSourceType(value as SourceType | "all");
                        setPage(1);
                      }}
                    />
                    <Select
                      aria-label="信源排序"
                      value={ordering}
                      style={{ width: 170 }}
                      options={[
                        { value: "-source_weight", label: "权重从高到低" },
                        { value: "-published_at", label: "发布时间从新到旧" },
                        { value: "best_rank", label: "检索位置优先" },
                        { value: "-authority_score", label: "来源权威优先" },
                      ]}
                      onChange={(value) => {
                        setOrdering(value);
                        setPage(1);
                      }}
                    />
                  </Space>
                }
              >
                <Table<SourceIndexItem>
                  rowKey="id"
                  columns={columns}
                  dataSource={items}
                  loading={itemsLoading}
                  pagination={false}
                  scroll={{ x: 1120 }}
                  locale={{ emptyText: "当前筛选条件下没有信源" }}
                />
                {itemCount > PAGE_SIZE ? (
                  <div className={styles.pagination}>
                    <Pagination
                      current={page}
                      pageSize={PAGE_SIZE}
                      total={itemCount}
                      showSizeChanger={false}
                      onChange={setPage}
                    />
                  </div>
                ) : null}
              </Card>

              <Card className={styles.scanMeta}>
                <Row gutter={[16, 16]}>
                  <Col xs={12} md={4}>
                    <Statistic title="原始结果" value={latestResult.raw_result_count} />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic title="链接去重后" value={latestResult.unique_result_count} />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic title="有效公开信源" value={latestResult.public_source_count} />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic title="搜索请求" value={latestResult.provider_request_count} />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic title="查询主题" value={latestResult.query_count} />
                  </Col>
                  <Col xs={12} md={4}>
                    <Statistic
                      title="扫描耗时"
                      value={formatElapsed(latestResult.elapsed_seconds)}
                    />
                  </Col>
                </Row>
                <Alert
                  className={styles.scopeNote}
                  type="info"
                  showIcon
                  message="数据口径"
                  description="页面展示的是本次百度公开搜索扫描实际发现并验证为与主体相关的公开信源，不宣称穷尽整个互联网。"
                />
              </Card>
            </>
          )}
        </>
      )}
    </main>
  );
}
