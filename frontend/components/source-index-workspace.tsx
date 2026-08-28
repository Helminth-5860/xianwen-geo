"use client";

import {
  FileSearchOutlined,
  GlobalOutlined,
  InfoCircleOutlined,
  LinkOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Empty,
  Pagination,
  Popover,
  Progress,
  Select,
  Skeleton,
  Space,
  Table,
  Tag,
  Tooltip,
  Typography,
  message,
} from "antd";
import type { ColumnsType } from "antd/es/table";
import { useCallback, useEffect, useMemo, useState } from "react";

import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getSourceIndexScan,
  getSourceIndexSources,
  getSubjectSourceIndex,
  isSourceIndexScanActive,
  isSourceIndexScanUsable,
  startSourceIndexScan,
  type QueryCoverageRow,
  type SourceIndexItem,
  type SourceIndexOrdering,
  type SourceIndexScanSummary,
  type SourceType,
  type SourceTypeDistributionRow,
  type SubjectSourceIndexState,
  type TopSourceRow,
} from "@/lib/source-index-client";

import styles from "./source-index-workspace.module.css";

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

const SCAN_STAGE_LABELS: Record<SourceIndexScanSummary["stage"], string> = {
  preparing: "正在构建主体搜索词",
  searching: "正在发现公开信源",
  classifying: "正在去重与识别来源",
  scoring: "正在计算信源权重与指数",
  completed: "扫描已完成",
};

const ERROR_MESSAGES: Record<string, string> = {
  BAIDU_SEARCH_API_KEY_MISSING: "当前尚未配置百度公开搜索凭据，请联系管理员完成配置。",
  BAIDU_SEARCH_AUTH_FAILED: "百度公开搜索授权校验失败，请检查搜索凭据。",
  BAIDU_SEARCH_RATE_LIMITED: "百度公开搜索当前请求较多，本次扫描未能完整完成。",
  BAIDU_SEARCH_NETWORK_ERROR: "公开搜索网络暂时不可用，请稍后重新扫描。",
  BAIDU_SEARCH_UPSTREAM_ERROR: "百度公开搜索服务暂时异常，请稍后重新扫描。",
  BAIDU_SEARCH_NO_USABLE_RESULTS: "本次公开搜索未获得可用结果。",
  SOURCE_INDEX_SUBJECT_IDENTITY_MISSING: "当前主体缺少可用于公开搜索的名称或品牌信息。",
  SOURCE_INDEX_TIMEOUT: "本次扫描超过最大处理时间，已停止继续搜索。",
  SOURCE_INDEX_FAILED: "本次信源扫描未完成，请稍后重试。",
};

const fmtNumber = (value: number | undefined | null) =>
  new Intl.NumberFormat("zh-CN").format(value ?? 0);

const fmtDateTime = (value: string | null | undefined) => {
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
};

const fmtDate = (value: string | null | undefined) => {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "—";
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(date);
};

const terminalStatus = (status: SourceIndexScanSummary["status"]) =>
  !isSourceIndexScanActive(status);

function ScoreExplanation({ item }: { item: SourceIndexItem }) {
  return (
    <div className={styles.scoreBreakdown}>
      <div>
        <span>来源权威度</span>
        <strong>{item.authority_score}</strong>
      </div>
      <div>
        <span>主体相关度</span>
        <strong>{item.relevance_score}</strong>
      </div>
      <div>
        <span>搜索可见度</span>
        <strong>{item.visibility_score}</strong>
      </div>
      <div>
        <span>内容新鲜度</span>
        <strong>{item.freshness_score}</strong>
      </div>
      <div className={styles.scoreFormula}>综合权重由固定公式计算，不由 AI 主观打分。</div>
    </div>
  );
}

function MetricCard({
  label,
  value,
  hint,
  emphasize = false,
}: {
  label: string;
  value: string | number;
  hint?: string;
  emphasize?: boolean;
}) {
  return (
    <div className={`${styles.metricCard} ${emphasize ? styles.metricPrimary : ""}`}>
      <div className={styles.metricLabel}>
        <span>{label}</span>
        {hint ? (
          <Tooltip title={hint}>
            <InfoCircleOutlined />
          </Tooltip>
        ) : null}
      </div>
      <div className={styles.metricValue}>{value}</div>
    </div>
  );
}

export function SourceIndexWorkspace() {
  const { currentSubject, loading: subjectLoading } = useSubjectWorkspace();
  const [messageApi, messageHolder] = message.useMessage();
  const [state, setState] = useState<SubjectSourceIndexState | null>(null);
  const [activeScan, setActiveScan] = useState<SourceIndexScanSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [sources, setSources] = useState<SourceIndexItem[]>([]);
  const [sourceCount, setSourceCount] = useState(0);
  const [sourcesLoading, setSourcesLoading] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sourceType, setSourceType] = useState<SourceType | undefined>();
  const [ordering, setOrdering] = useState<SourceIndexOrdering>("-source_weight");

  const latest = state?.latest_result ?? null;

  const loadState = useCallback(async (subjectId: string, quiet = false) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const next = await getSubjectSourceIndex(subjectId);
      setState(next);
      setActiveScan(next.active_scan);
      return next;
    } catch (reason: unknown) {
      setError(userMessage(reason));
      return null;
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!currentSubject?.id) {
      setState(null);
      setActiveScan(null);
      setSources([]);
      setSourceCount(0);
      return;
    }
    setPage(1);
    void loadState(currentSubject.id);
  }, [currentSubject?.id, loadState]);

  useEffect(() => {
    if (!activeScan || !isSourceIndexScanActive(activeScan.status) || !currentSubject?.id) return;
    let alive = true;
    const timer = window.setInterval(() => {
      void getSourceIndexScan(activeScan.id)
        .then(async (scan) => {
          if (!alive) return;
          setActiveScan(scan);
          if (terminalStatus(scan.status)) {
            window.clearInterval(timer);
            const refreshed = await loadState(currentSubject.id, true);
            if (!alive || !refreshed) return;
            if (isSourceIndexScanUsable(scan.status)) {
              messageApi.success(
                scan.status === "limit_reached"
                  ? "已达到扫描上限，并基于当前发现结果完成分析"
                  : "公开信源扫描完成",
              );
            } else if (scan.status === "failed") {
              messageApi.warning(
                ERROR_MESSAGES[scan.stable_error_code] ?? "本次信源扫描未完成",
              );
            }
          }
        })
        .catch(() => undefined);
    }, 1800);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [activeScan, currentSubject?.id, loadState, messageApi]);

  const loadSources = useCallback(async () => {
    if (!latest?.id) {
      setSources([]);
      setSourceCount(0);
      return;
    }
    setSourcesLoading(true);
    try {
      const response = await getSourceIndexSources(latest.id, {
        page,
        pageSize,
        sourceType,
        ordering,
      });
      setSources(response.results);
      setSourceCount(response.count);
    } catch (reason: unknown) {
      messageApi.warning(userMessage(reason));
    } finally {
      setSourcesLoading(false);
    }
  }, [latest?.id, messageApi, ordering, page, pageSize, sourceType]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  const beginScan = async () => {
    if (
      !currentSubject?.id ||
      starting ||
      (activeScan && isSourceIndexScanActive(activeScan.status))
    ) {
      return;
    }
    setStarting(true);
    setError("");
    try {
      const scan = await startSourceIndexScan(currentSubject.id);
      setActiveScan(scan);
      setState((current) =>
        current
          ? { ...current, active_scan: scan }
          : { active_scan: scan, latest_result: null },
      );
      messageApi.success("已开始扫描公开网络信源");
    } catch (reason: unknown) {
      const text = userMessage(reason);
      setError(text);
      messageApi.warning(text);
    } finally {
      setStarting(false);
    }
  };

  const typeDistribution = useMemo(() => {
    const rows = latest?.source_type_distribution ?? [];
    const total = rows.reduce((sum, row) => sum + row.count, 0);
    return rows.map((row) => ({
      ...row,
      percent: total ? Math.round((row.count / total) * 1000) / 10 : 0,
    }));
  }, [latest?.source_type_distribution]);

  const sourceColumns: ColumnsType<SourceIndexItem> = [
    {
      title: "来源",
      key: "source",
      width: 190,
      render: (_, item) => (
        <div className={styles.sourceIdentity}>
          <Typography.Text strong ellipsis={{ tooltip: item.website || item.root_domain }}>
            {item.website || item.root_domain}
          </Typography.Text>
          <Typography.Text
            type="secondary"
            className={styles.domainText}
            ellipsis={{ tooltip: item.root_domain }}
          >
            {item.root_domain}
          </Typography.Text>
        </div>
      ),
    },
    {
      title: "标题",
      dataIndex: "title",
      key: "title",
      render: (title: string, item) => (
        <div className={styles.titleCell}>
          <a
            href={item.original_url}
            target="_blank"
            rel="noopener noreferrer"
            className={styles.sourceTitle}
          >
            {title}
          </a>
          {item.repost_cluster_id ? <Tag bordered={false}>疑似转载簇</Tag> : null}
        </div>
      ),
    },
    {
      title: "类型",
      dataIndex: "source_type",
      key: "source_type",
      width: 135,
      render: (value: SourceType) => <Tag>{SOURCE_TYPE_LABELS[value] ?? "其他"}</Tag>,
    },
    {
      title: "发布时间",
      dataIndex: "published_at",
      key: "published_at",
      width: 125,
      render: (value: string | null) => fmtDate(value),
    },
    {
      title: "检索位置",
      dataIndex: "best_rank",
      key: "best_rank",
      width: 105,
      render: (value: number) => (value <= 50 ? `#${value}` : "时间切片"),
    },
    {
      title: "信源权重",
      dataIndex: "source_weight",
      key: "source_weight",
      width: 120,
      render: (value: string, item) => (
        <Popover title="信源权重构成" content={<ScoreExplanation item={item} />}>
          <Button type="link" className={styles.scoreButton}>
            {Number(value).toFixed(1)}
          </Button>
        </Popover>
      ),
    },
    {
      title: "原文",
      key: "link",
      width: 80,
      render: (_, item) => (
        <Tooltip title="打开原始网页">
          <Button
            type="text"
            icon={<LinkOutlined />}
            href={item.original_url}
            target="_blank"
            rel="noopener noreferrer"
          />
        </Tooltip>
      ),
    },
  ];

  const queryColumns: ColumnsType<QueryCoverageRow> = [
    { title: "查询主题", dataIndex: "query", key: "query" },
    { title: "发现信源", dataIndex: "source_count", key: "source_count", width: 110 },
    {
      title: "独立来源",
      dataIndex: "independent_source_count",
      key: "independent_source_count",
      width: 110,
    },
    {
      title: "本次最好位置",
      dataIndex: "best_rank",
      key: "best_rank",
      width: 130,
      render: (value: number | null) => (value ? `#${value}` : "仅时间切片发现"),
    },
  ];

  const topSourceColumns: ColumnsType<TopSourceRow> = [
    { title: "来源域名", dataIndex: "root_domain", key: "root_domain" },
    {
      title: "类型",
      dataIndex: "source_type",
      key: "source_type",
      width: 150,
      render: (value: SourceType) => SOURCE_TYPE_LABELS[value] ?? "其他",
    },
    { title: "信源数", dataIndex: "source_count", key: "source_count", width: 100 },
    {
      title: "平均权重",
      dataIndex: "average_weight",
      key: "average_weight",
      width: 110,
      render: (value: number) => value.toFixed(1),
    },
  ];

  if (subjectLoading) {
    return (
      <main className="page-shell">
        <Skeleton active paragraph={{ rows: 8 }} />
      </main>
    );
  }

  if (!currentSubject) {
    return (
      <main className="page-shell">
        {messageHolder}
        <Empty description="请先选择一个主体，再查看公开信源" />
      </main>
    );
  }

  if (loading && !state) {
    return (
      <main className="page-shell">
        <Skeleton active paragraph={{ rows: 8 }} />
      </main>
    );
  }

  const running = Boolean(activeScan && isSourceIndexScanActive(activeScan.status));
  const scanProgress = activeScan?.progress ?? {};
  const errorMessage = activeScan?.stable_error_code
    ? ERROR_MESSAGES[activeScan.stable_error_code] ?? "本次扫描未完整完成。"
    : "";

  return (
    <main className="page-shell">
      {messageHolder}
      <div className={styles.headerRow}>
        <div>
          <Space size="small" align="center">
            <GlobalOutlined className={styles.headerIcon} />
            <Typography.Title level={2} className={styles.pageTitle}>
              信源指数
            </Typography.Title>
          </Space>
          <Typography.Paragraph type="secondary" className={styles.subtitle}>
            扫描公开网络中与当前主体相关的可发现信源，分析外部曝光、独立来源与媒体覆盖。仅使用公开搜索元数据，不抓取文章全文。
          </Typography.Paragraph>
        </div>
        <Button
          type="primary"
          icon={<ReloadOutlined spin={running} />}
          loading={starting}
          disabled={running}
          onClick={() => void beginScan()}
        >
          {running ? "正在扫描" : latest ? "更新信源" : "开始扫描"}
        </Button>
      </div>

      {error ? <Alert type="error" showIcon message={error} className={styles.alert} /> : null}
      {activeScan?.status === "failed" && errorMessage ? (
        <Alert type="warning" showIcon message={errorMessage} className={styles.alert} />
      ) : null}

      {running && activeScan ? (
        <Card className={styles.scanCard}>
          <div className={styles.scanHeader}>
            <div>
              <Typography.Text strong>{SCAN_STAGE_LABELS[activeScan.stage]}</Typography.Text>
              <div className={styles.scanHint}>
                发现趋于饱和后会自动结束；复杂主体最长约 5 分钟。
              </div>
            </div>
            <Tag color="processing">百度公开搜索</Tag>
          </div>
          <div className={styles.liveMetrics}>
            <div>
              <span>原始结果</span>
              <strong>{fmtNumber(scanProgress.raw ?? activeScan.raw_result_count)}</strong>
            </div>
            <div>
              <span>去重结果</span>
              <strong>{fmtNumber(scanProgress.unique ?? activeScan.unique_result_count)}</strong>
            </div>
            <div>
              <span>已请求</span>
              <strong>{fmtNumber(activeScan.provider_request_count)}</strong>
            </div>
            <div>
              <span>待搜索分支</span>
              <strong>{fmtNumber(scanProgress.queries_remaining)}</strong>
            </div>
          </div>
          <div className={styles.stageTrack}>
            {["preparing", "searching", "classifying", "scoring"].map((stage, index) => {
              const order = ["preparing", "searching", "classifying", "scoring", "completed"];
              const reached = order.indexOf(activeScan.stage) >= index;
              return (
                <span
                  key={stage}
                  className={reached ? styles.stageReached : styles.stagePending}
                >
                  {index + 1}
                </span>
              );
            })}
          </div>
        </Card>
      ) : null}

      {!latest ? (
        <Card className={styles.emptyCard}>
          <Empty
            image={<FileSearchOutlined className={styles.emptyIcon} />}
            description={
              <Space direction="vertical" size={4}>
                <Typography.Text strong>尚未扫描公开信源</Typography.Text>
                <Typography.Text type="secondary">
                  开始扫描后，系统会自动判断何时已接近饱和，无需手动选择扫描深度。
                </Typography.Text>
              </Space>
            }
          >
            <Button
              type="primary"
              loading={starting}
              disabled={running}
              onClick={() => void beginScan()}
            >
              开始扫描
            </Button>
          </Empty>
        </Card>
      ) : (
        <>
          {latest.status === "partial" ? (
            <Alert
              type="warning"
              showIcon
              message="部分公开搜索请求未完成，本次数据可能不完整。"
              className={styles.alert}
            />
          ) : null}
          {latest.status === "limit_reached" ? (
            <Alert
              type="info"
              showIcon
              message="本次扫描已达到安全上限，并基于当前已发现信源完成分析。"
              className={styles.alert}
            />
          ) : null}

          <div className={styles.metricGrid}>
            <MetricCard
              label="信源指数"
              value={latest.index_score ? Number(latest.index_score).toFixed(1) : "0.0"}
              emphasize
              hint="基于当前扫描发现的有效信源规模、独立来源、来源权威度、搜索可见度和新鲜度综合计算。"
            />
            <MetricCard
              label="公开信源"
              value={fmtNumber(latest.public_source_count)}
              hint="当前扫描去重并通过主体相关性过滤后的有效公开信源。"
            />
            <MetricCard
              label="独立来源"
              value={fmtNumber(latest.independent_domain_count)}
              hint="有效信源来自的独立根域名数量。"
            />
            <MetricCard
              label="新闻 / 媒体"
              value={fmtNumber(latest.news_media_count)}
              hint="新闻媒体与行业媒体类型的有效信源数量。"
            />
            <MetricCard
              label="高权重信源"
              value={fmtNumber(latest.high_weight_count)}
              hint="当前算法下信源权重达到高权重阈值的结果。"
            />
            <MetricCard
              label="近30天发布"
              value={fmtNumber(latest.recent_30d_count)}
              hint="能够识别发布时间且发布时间位于最近30天的有效信源。"
            />
          </div>

          <div className={styles.scanMeta}>
            <span>最近扫描：{fmtDateTime(latest.finished_at)}</span>
            <span>
              耗时：{latest.elapsed_seconds == null ? "—" : `${latest.elapsed_seconds.toFixed(1)} 秒`}
            </span>
            <span>搜索请求：{fmtNumber(latest.provider_request_count)} 次</span>
            <span>原始结果：{fmtNumber(latest.raw_result_count)}</span>
            <span>去重候选：{fmtNumber(latest.unique_result_count)}</span>
          </div>

          <div className={styles.twoColumnGrid}>
            <Card title="来源类型分布" className={styles.sectionCard}>
              {!typeDistribution.length ? (
                <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} />
              ) : (
                <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                  {typeDistribution.map((row: SourceTypeDistributionRow & { percent: number }) => (
                    <div key={row.source_type} className={styles.distributionRow}>
                      <div className={styles.distributionLabel}>
                        <span>{SOURCE_TYPE_LABELS[row.source_type]}</span>
                        <strong>{fmtNumber(row.count)}</strong>
                      </div>
                      <Progress percent={row.percent} showInfo={false} size="small" />
                    </div>
                  ))}
                </Space>
              )}
            </Card>

            <Card
              title={
                <Space size="small">
                  <SafetyCertificateOutlined />
                  <span>指数构成</span>
                </Space>
              }
              className={styles.sectionCard}
            >
              <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                {[
                  ["曝光规模", latest.factor_scores.exposure ?? 0],
                  ["独立来源多样性", latest.factor_scores.diversity ?? 0],
                  ["来源权威", latest.factor_scores.authority ?? 0],
                  ["搜索可见度", latest.factor_scores.visibility ?? 0],
                  ["新鲜度", latest.factor_scores.freshness ?? 0],
                ].map(([label, value]) => (
                  <div key={String(label)} className={styles.factorRow}>
                    <span>{label}</span>
                    <Progress
                      percent={Number(value)}
                      size="small"
                      format={(percent) => `${Number(percent).toFixed(0)}`}
                    />
                  </div>
                ))}
                <Typography.Text type="secondary" className={styles.formulaNote}>
                  信源指数采用固定版本公式计算，数量因素使用饱和处理，避免大量重复或低价值内容线性刷高得分。
                </Typography.Text>
              </Space>
            </Card>
          </div>

          <div className={styles.twoColumnGrid}>
            <Card title="关键词曝光" className={styles.sectionCard}>
              <Table<QueryCoverageRow>
                size="small"
                rowKey="query"
                columns={queryColumns}
                dataSource={latest.query_coverage}
                pagination={false}
                scroll={{ x: 620 }}
              />
            </Card>
            <Card title="TOP 来源" className={styles.sectionCard}>
              <Table<TopSourceRow>
                size="small"
                rowKey={(row) => `${row.root_domain}-${row.source_type}`}
                columns={topSourceColumns}
                dataSource={latest.top_sources}
                pagination={false}
                scroll={{ x: 520 }}
              />
            </Card>
          </div>

          <Card title="信源明细" className={styles.sectionCard}>
            <div className={styles.tableToolbar}>
              <Space wrap>
                <Select<SourceType | undefined>
                  allowClear
                  placeholder="全部来源类型"
                  value={sourceType}
                  style={{ width: 180 }}
                  options={Object.entries(SOURCE_TYPE_LABELS).map(([value, label]) => ({
                    value: value as SourceType,
                    label,
                  }))}
                  onChange={(value) => {
                    setSourceType(value);
                    setPage(1);
                  }}
                />
                <Select<SourceIndexOrdering>
                  value={ordering}
                  style={{ width: 170 }}
                  options={[
                    { value: "-source_weight", label: "权重从高到低" },
                    { value: "-published_at", label: "发布时间最新" },
                    { value: "best_rank", label: "检索位置靠前" },
                    { value: "-authority_score", label: "来源权威度优先" },
                  ]}
                  onChange={(value) => {
                    setOrdering(value);
                    setPage(1);
                  }}
                />
              </Space>
              <Typography.Text type="secondary">
                当前筛选 {fmtNumber(sourceCount)} 条
              </Typography.Text>
            </div>
            <Table<SourceIndexItem>
              rowKey="id"
              columns={sourceColumns}
              dataSource={sources}
              loading={sourcesLoading}
              pagination={false}
              scroll={{ x: 1080 }}
              locale={{ emptyText: "当前筛选条件下暂无信源" }}
            />
            <div className={styles.paginationRow}>
              <Pagination
                current={page}
                pageSize={pageSize}
                total={sourceCount}
                showSizeChanger
                pageSizeOptions={[20, 50, 100]}
                showTotal={(total) => `共 ${fmtNumber(total)} 条`}
                onChange={(nextPage, nextPageSize) => {
                  setPageSize(nextPageSize);
                  setPage(nextPageSize === pageSize ? nextPage : 1);
                }}
              />
            </div>
          </Card>
        </>
      )}
    </main>
  );
}
