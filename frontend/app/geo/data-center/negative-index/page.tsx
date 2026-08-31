"use client";

import {
  ExportOutlined,
  InfoCircleOutlined,
  ReloadOutlined,
  SafetyCertificateOutlined,
  WarningOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Col,
  Empty,
  Modal,
  Pagination,
  Progress,
  Row,
  Select,
  Skeleton,
  Space,
  Statistic,
  Table,
  Tag,
  Tooltip,
  Typography,
  type TableProps,
} from "antd";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { QuotaActionHint } from "@/components/quota-action-hint";
import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import { userMessage } from "@/lib/auth-client";
import {
  getNegativeEvent,
  getNegativeIndexEvents,
  getNegativeIndexScan,
  getNegativeIndexState,
  startNegativeIndexScan,
  type NegativeCategory,
  type NegativeClaimType,
  type NegativeEvent,
  type NegativeEventDetail,
  type NegativeEventStatus,
  type NegativeIndexScanSummary,
  type NegativeIndexState,
} from "@/lib/negative-index-client";

import styles from "./negative-index.module.css";

const { Paragraph, Text, Title } = Typography;
const PAGE_SIZE = 20;

const CATEGORY_LABELS: Record<NegativeCategory, string> = {
  regulatory: "监管处罚",
  judicial: "司法风险",
  consumer_complaint: "消费者投诉",
  product_service_incident: "产品/服务事故",
  business_operation: "经营风险",
  media_negative: "媒体负面",
  online_opinion: "网络舆情",
  other: "其他",
};

const STATUS_LABELS: Record<NegativeEventStatus, string> = {
  suspected: "疑似",
  reported: "已报道",
  confirmed: "已确认",
  disputed: "存在争议",
  resolved: "已解决",
  retracted: "已撤回",
  false_positive: "误判",
};

const CLAIM_LABELS: Record<NegativeClaimType, string> = {
  official_finding: "官方结论",
  reported_fact: "媒体事实报道",
  reported_claim: "媒体转述指控",
  user_allegation: "用户指控",
  opinion: "观点",
  rumor: "传闻",
  rebuttal: "回应/澄清",
};

const STAGE_LABELS: Record<NegativeIndexScanSummary["stage"], string> = {
  preparing: "正在准备主体信息",
  searching: "正在扫描公开网络",
  classifying: "正在识别负面风险",
  verifying: "正在核验高风险候选",
  clustering: "正在归并重复事件",
  scoring: "正在计算风险指数",
  completed: "扫描已完成",
};

const STAGE_PROGRESS: Record<NegativeIndexScanSummary["stage"], number> = {
  preparing: 5,
  searching: 30,
  classifying: 55,
  verifying: 72,
  clustering: 84,
  scoring: 94,
  completed: 100,
};

const RISK_LABELS = {
  low: "低风险",
  watch: "关注",
  elevated: "较高风险",
  high: "高风险",
} as const;

const RISK_TAG_COLORS = {
  low: "green",
  watch: "gold",
  elevated: "orange",
  high: "red",
} as const;

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

function stableErrorMessage(code: string) {
  const messages: Record<string, string> = {
    BAIDU_SEARCH_API_KEY_MISSING: "公开信息查询服务尚未配置，请联系管理员。",
    BAIDU_SEARCH_CREDENTIAL_INVALID: "公开信息查询服务配置异常，请联系管理员。",
    BAIDU_SEARCH_AUTH_HEADER_INVALID: "公开信息查询服务配置异常，请联系管理员。",
    BAIDU_SEARCH_AUTH_FAILED: "公开信息查询服务暂时不可用，请联系管理员检查配置。",
    BAIDU_SEARCH_RATE_LIMITED: "公开信息查询较为繁忙，请稍后重新扫描。",
    BAIDU_SEARCH_NETWORK_ERROR: "公开搜索网络暂时不可用，请稍后重试。",
    BAIDU_SEARCH_UPSTREAM_ERROR: "公开信息查询服务暂时不可用，请稍后重试。",
    BAIDU_SEARCH_BAD_REQUEST: "本次公开信息查询未能完成，请稍后重新扫描。",
    BAIDU_SEARCH_INVALID_JSON: "公开信息查询结果暂时不可用，请稍后重新扫描。",
    BAIDU_SEARCH_PROVIDER_ERROR: "公开信息查询服务暂时不可用，请稍后重试。",
    BAIDU_SEARCH_NO_USABLE_RESULTS: "本次未找到可用于分析的公开信息，请稍后重试。",
    NEGATIVE_INDEX_SUBJECT_IDENTITY_MISSING: "当前主体缺少可用于公开搜索的企业名称或品牌名称。",
    NEGATIVE_INDEX_TIMEOUT: "上一次扫描异常中断，请重新发起扫描。",
  };
  return messages[code] ?? "负面信息扫描未完成，请稍后重新扫描。";
}

function statusNotice(result: NegativeIndexScanSummary) {
  if (result.status === "limit_reached") {
    return (
      <Alert
        type="info"
        showIcon
        message="本次扫描已达到最大检索边界"
        description="系统已基于当前发现的公开信息完成风险分析；达到时间或请求边界不等于扫描失败。"
      />
    );
  }
  if (result.status === "partial") {
    return (
      <Alert
        type="warning"
        showIcon
        message="本次结果为部分结果"
        description="部分公开信息查询、智能语义分析或高风险内容核验未完成。已保留可验证结果，但覆盖范围可能低于正常扫描。"
      />
    );
  }
  return null;
}

function riskNumber(value: string | null) {
  const parsed = Number(value ?? 0);
  return Number.isFinite(parsed) ? parsed : 0;
}

export default function NegativeIndexPage() {
  const { currentSubject: subject, loading: subjectLoading } = useSubjectWorkspace();

  if (subjectLoading) {
    return (
      <main className={styles.page}>
        <Skeleton active />
      </main>
    );
  }

  if (!subject) {
    return (
      <main className={styles.page}>
        <Empty description="请先选择或创建主体，再进行负面信息扫描。" />
      </main>
    );
  }

  return <NegativeIndexSubjectPage key={subject.id} subjectId={subject.id} />;
}

function NegativeIndexSubjectPage({ subjectId }: Readonly<{ subjectId: string }>) {
  const [state, setState] = useState<NegativeIndexState | null>(null);
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState("");
  const [page, setPage] = useState(1);
  const [category, setCategory] = useState<NegativeCategory | "all">("all");
  const [eventStatus, setEventStatus] = useState<NegativeEventStatus | "all">("all");
  const [events, setEvents] = useState<NegativeEvent[]>([]);
  const [eventCount, setEventCount] = useState(0);
  const [eventsKey, setEventsKey] = useState("");
  const [detail, setDetail] = useState<NegativeEventDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailResultId, setDetailResultId] = useState("");
  const mountedRef = useRef(true);
  const stateRequestRef = useRef(0);
  const eventRequestRef = useRef(0);
  const detailRequestRef = useRef(0);
  const startRequestRef = useRef(0);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      stateRequestRef.current += 1;
      eventRequestRef.current += 1;
      detailRequestRef.current += 1;
      startRequestRef.current += 1;
    };
  }, []);

  const loadState = useCallback(
    async (targetSubjectId: string) => {
      const requestId = stateRequestRef.current;
      const result = await getNegativeIndexState(targetSubjectId);
      if (
        !mountedRef.current ||
        subjectId !== targetSubjectId ||
        stateRequestRef.current !== requestId
      ) {
        return null;
      }
      setState(result);
      return result;
    },
    [subjectId],
  );

  useEffect(() => {
    let current = true;
    const requestId = stateRequestRef.current;
    void getNegativeIndexState(subjectId)
      .then((result) => {
        if (current && mountedRef.current && stateRequestRef.current === requestId) {
          setState(result);
        }
      })
      .catch((reason: unknown) => {
        if (current && mountedRef.current && stateRequestRef.current === requestId) {
          setState(null);
          setError(userMessage(reason));
        }
      })
      .finally(() => {
        if (current && mountedRef.current && stateRequestRef.current === requestId) {
          setLoading(false);
        }
      });
    return () => {
      current = false;
    };
  }, [subjectId]);

  const activeScan = state?.active_scan ?? null;
  const latestResult = state?.latest_result ?? null;
  const eventQueryKey = latestResult?.id
    ? `${latestResult.id}|${page}|${category}|${eventStatus}`
    : "";
  const visibleEvents = eventsKey === eventQueryKey ? events : [];
  const visibleEventCount = eventsKey === eventQueryKey ? eventCount : 0;
  const eventsLoading = Boolean(eventQueryKey) && eventsKey !== eventQueryKey;
  const visibleDetail = detailResultId && detailResultId === latestResult?.id ? detail : null;
  const visibleDetailLoading =
    Boolean(detailResultId) && detailResultId === latestResult?.id && detailLoading;

  useEffect(() => {
    if (!subjectId || !activeScan?.id) return;
    let cancelled = false;
    let timer = 0;
    const targetSubjectId = subjectId;
    const requestId = stateRequestRef.current;
    const poll = async () => {
      try {
        const scan = await getNegativeIndexScan(activeScan.id);
        if (
          cancelled ||
          !mountedRef.current ||
          stateRequestRef.current !== requestId ||
          scan.subject_id !== targetSubjectId
        ) {
          return;
        }
        if (["queued", "running"].includes(scan.status)) {
          setState((current) =>
            current?.active_scan?.id === scan.id ? { ...current, active_scan: scan } : current,
          );
          timer = window.setTimeout(() => void poll(), 1800);
          return;
        }
        const refreshed = await loadState(targetSubjectId);
        if (
          cancelled ||
          !refreshed ||
          !mountedRef.current ||
          stateRequestRef.current !== requestId
        ) {
          return;
        }
        if (scan.status === "failed") {
          setError(stableErrorMessage(scan.stable_error_code));
        } else if (refreshed.latest_result) {
          setError("");
          setPage(1);
        }
      } catch (reason: unknown) {
        if (!cancelled && mountedRef.current && stateRequestRef.current === requestId) {
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
    const requestId = ++eventRequestRef.current;
    if (!latestResult?.id || latestResult.subject_id !== subjectId) {
      return;
    }
    let current = true;
    const targetQueryKey = eventQueryKey;
    void getNegativeIndexEvents(latestResult.id, {
      page,
      pageSize: PAGE_SIZE,
      category: category === "all" ? undefined : category,
      status: eventStatus === "all" ? undefined : eventStatus,
      ordering: "-current_risk",
    })
      .then((result) => {
        if (!current || !mountedRef.current || eventRequestRef.current !== requestId) {
          return;
        }
        setEventsKey(targetQueryKey);
        setEvents(result.results);
        setEventCount(result.count);
      })
      .catch((reason: unknown) => {
        if (current && mountedRef.current && eventRequestRef.current === requestId) {
          setEventsKey(targetQueryKey);
          setEvents([]);
          setEventCount(0);
          setError(userMessage(reason));
        }
      });
    return () => {
      current = false;
    };
  }, [
    category,
    eventQueryKey,
    eventStatus,
    latestResult?.id,
    latestResult?.subject_id,
    page,
    subjectId,
  ]);

  const startScan = async () => {
    if (!subjectId || starting || activeScan) return;
    const targetSubjectId = subjectId;
    const requestId = ++startRequestRef.current;
    setStarting(true);
    setError("");
    try {
      const scan = await startNegativeIndexScan(targetSubjectId);
      if (
        !mountedRef.current ||
        startRequestRef.current !== requestId ||
        scan.subject_id !== targetSubjectId
      ) {
        return;
      }
      setState((current) => ({
        active_scan: scan,
        latest_result: current?.latest_result ?? null,
        history: current?.history ?? [],
      }));
    } catch (reason: unknown) {
      if (mountedRef.current && startRequestRef.current === requestId) {
        setError(userMessage(reason));
      }
    } finally {
      if (mountedRef.current && startRequestRef.current === requestId) {
        setStarting(false);
      }
    }
  };

  const openDetail = async (event: NegativeEvent) => {
    const targetSubjectId = subjectId;
    const targetResultId = latestResult?.id ?? "";
    const requestId = ++detailRequestRef.current;
    setDetailResultId(targetResultId);
    setDetail(null);
    setDetailLoading(true);
    try {
      const result = await getNegativeEvent(event.id);
      if (
        mountedRef.current &&
        subjectId === targetSubjectId &&
        detailRequestRef.current === requestId &&
        latestResult?.id === targetResultId
      ) {
        setDetail(result);
      }
    } catch (reason: unknown) {
      if (
        mountedRef.current &&
        subjectId === targetSubjectId &&
        detailRequestRef.current === requestId
      ) {
        setError(userMessage(reason));
      }
    } finally {
      if (
        mountedRef.current &&
        subjectId === targetSubjectId &&
        detailRequestRef.current === requestId
      ) {
        setDetailLoading(false);
      }
    }
  };

  const closeDetail = () => {
    detailRequestRef.current += 1;
    setDetailResultId("");
    setDetail(null);
    setDetailLoading(false);
  };

  const categoryTotal = useMemo(
    () => latestResult?.category_distribution.reduce((sum, item) => sum + item.count, 0) ?? 0,
    [latestResult?.category_distribution],
  );

  const trend = useMemo(() => [...(state?.history ?? [])].reverse().slice(-20), [state?.history]);

  const columns: TableProps<NegativeEvent>["columns"] = [
    {
      title: "风险",
      dataIndex: "current_risk",
      width: 90,
      render: (value: string) => <Text strong>{Math.round(riskNumber(value))}</Text>,
      sorter: false,
    },
    {
      title: "负面风险事件",
      dataIndex: "title",
      render: (_value, record) => (
        <Button type="link" className={styles.eventLink} onClick={() => void openDetail(record)}>
          {record.title}
        </Button>
      ),
    },
    {
      title: "类型",
      dataIndex: "category",
      width: 130,
      render: (value: NegativeCategory) => <Tag>{CATEGORY_LABELS[value]}</Tag>,
    },
    {
      title: "证据性质",
      dataIndex: "claim_type",
      width: 150,
      render: (value: NegativeClaimType) => CLAIM_LABELS[value],
    },
    {
      title: "状态",
      dataIndex: "status",
      width: 110,
      render: (value: NegativeEventStatus) => (
        <Tag color={value === "confirmed" ? "red" : value === "disputed" ? "gold" : undefined}>
          {STATUS_LABELS[value]}
        </Tag>
      ),
    },
    {
      title: "信源",
      dataIndex: "source_count",
      width: 90,
      render: (value: number, record) => (
        <Tooltip title={`${record.independent_domain_count} 个独立域名`}>
          <span>{value}</span>
        </Tooltip>
      ),
    },
    {
      title: "最近发现",
      dataIndex: "last_seen_at",
      width: 120,
      render: (value: string | null) => formatDate(value),
    },
  ];

  if (loading) {
    return (
      <main className={styles.page}>
        <Skeleton active />
      </main>
    );
  }

  return (
    <main className={styles.page}>
      <div className={styles.header}>
        <div>
          <Space align="center">
            <WarningOutlined />
            <Title level={2} className={styles.title}>
              负面信息指数
            </Title>
            <Tooltip title="0–100 分，分数越高表示当前公开负面风险暴露越高。">
              <InfoCircleOutlined />
            </Tooltip>
          </Space>
          <Paragraph type="secondary" className={styles.subtitle}>
            汇集公开网络信息，结合来源可信度、智能语义分析和高风险内容核验，分析当前主体的公开负面风险。
          </Paragraph>
        </div>
        <Space orientation="vertical" align="end" size={6}>
          <Button
            type="primary"
            icon={<ReloadOutlined />}
            loading={starting}
            disabled={Boolean(activeScan)}
            onClick={() => void startScan()}
          >
            {latestResult ? "重新扫描" : "开始扫描"}
          </Button>
          <QuotaActionHint
            quotaType="negative_index_scans"
            actionText="本次扫描获得有效结果后使用 1 次负面信息扫描额度"
          />
        </Space>
      </div>

      <Alert
        type="info"
        showIcon
        icon={<SafetyCertificateOutlined />}
        message="风险情报口径"
        description="本页展示的是本次扫描发现的公开负面风险信号，不代表司法或监管事实认定。投诉、指控、观点与传闻会保留其证据性质；回应、澄清和辟谣不会因包含负面关键词而被当成已证实事实。"
      />

      {error ? <Alert className={styles.block} type="error" showIcon message={error} /> : null}

      {activeScan ? (
        <Card className={styles.block}>
          <Space direction="vertical" size="small" className={styles.fullWidth}>
            <Space wrap>
              <Text strong>{STAGE_LABELS[activeScan.stage]}</Text>
              <Text type="secondary">已发现 {activeScan.unique_result_count} 个独立结果</Text>
              {activeScan.candidate_count ? (
                <Text type="secondary">待分析 {activeScan.candidate_count}</Text>
              ) : null}
            </Space>
            <Progress percent={STAGE_PROGRESS[activeScan.stage]} status="active" />
          </Space>
        </Card>
      ) : null}

      {latestResult ? (
        <>
          <div className={styles.block}>{statusNotice(latestResult)}</div>
          <Row gutter={[16, 16]} className={styles.block}>
            <Col xs={24} sm={12} xl={6}>
              <Card>
                <Statistic
                  title="公开负面风险指数"
                  value={riskNumber(latestResult.index_score)}
                  precision={0}
                  suffix="/ 100"
                />
                <Tag color={RISK_TAG_COLORS[latestResult.risk_level]}>
                  {RISK_LABELS[latestResult.risk_level]}
                </Tag>
              </Card>
            </Col>
            <Col xs={12} sm={6} xl={6}>
              <Card>
                <Statistic title="有效负面事件" value={latestResult.event_count} />
              </Card>
            </Col>
            <Col xs={12} sm={6} xl={6}>
              <Card>
                <Statistic title="高风险事件" value={latestResult.high_risk_event_count} />
              </Card>
            </Col>
            <Col xs={12} sm={6} xl={3}>
              <Card>
                <Statistic title="近30天" value={latestResult.recent_30d_event_count} />
              </Card>
            </Col>
            <Col xs={12} sm={6} xl={3}>
              <Card>
                <Statistic title="正文核验" value={latestResult.verified_item_count} />
              </Card>
            </Col>
          </Row>

          <Row gutter={[16, 16]} className={styles.block}>
            <Col xs={24} lg={14}>
              <Card
                title="风险指数趋势"
                extra={<Text type="secondary">最近 {trend.length} 次扫描</Text>}
              >
                {trend.length > 1 ? (
                  <div className={styles.trend}>
                    {trend.map((scan) => {
                      const score = riskNumber(scan.index_score);
                      return (
                        <Tooltip
                          key={scan.id}
                          title={`${formatDateTime(scan.finished_at)} · ${Math.round(score)} 分`}
                        >
                          <div className={styles.trendColumn}>
                            <div
                              className={styles.trendBar}
                              style={{ height: `${Math.max(3, score)}%` }}
                            />
                          </div>
                        </Tooltip>
                      );
                    })}
                  </div>
                ) : (
                  <Empty
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                    description="完成至少两次扫描后显示趋势"
                  />
                )}
              </Card>
            </Col>
            <Col xs={24} lg={10}>
              <Card title="风险类型构成">
                <Space direction="vertical" size="middle" className={styles.fullWidth}>
                  {latestResult.category_distribution.length ? (
                    latestResult.category_distribution.map((row) => {
                      if (!row.category) return null;
                      const percent = categoryTotal
                        ? Math.round((row.count / categoryTotal) * 100)
                        : 0;
                      return (
                        <div key={row.category}>
                          <div className={styles.distributionLabel}>
                            <Text>{CATEGORY_LABELS[row.category]}</Text>
                            <Text type="secondary">
                              {row.count} · {percent}%
                            </Text>
                          </div>
                          <Progress percent={percent} showInfo={false} size="small" />
                        </div>
                      );
                    })
                  ) : (
                    <Empty image={Empty.PRESENTED_IMAGE_SIMPLE} description="未发现有效负面事件" />
                  )}
                </Space>
              </Card>
            </Col>
          </Row>

          <Card
            className={styles.block}
            title="负面风险事件"
            extra={
              <Space wrap>
                <Select
                  value={category}
                  style={{ width: 150 }}
                  onChange={(value) => {
                    setCategory(value);
                    setPage(1);
                  }}
                  options={[
                    { value: "all", label: "全部类型" },
                    ...Object.entries(CATEGORY_LABELS).map(([value, label]) => ({ value, label })),
                  ]}
                />
                <Select
                  value={eventStatus}
                  style={{ width: 140 }}
                  onChange={(value) => {
                    setEventStatus(value);
                    setPage(1);
                  }}
                  options={[
                    { value: "all", label: "全部状态" },
                    ...Object.entries(STATUS_LABELS).map(([value, label]) => ({ value, label })),
                  ]}
                />
              </Space>
            }
          >
            <Table<NegativeEvent>
              rowKey="id"
              columns={columns}
              dataSource={visibleEvents}
              loading={eventsLoading}
              pagination={false}
              scroll={{ x: 1000 }}
              locale={{ emptyText: "本次扫描未发现符合当前筛选条件的负面风险事件" }}
            />
            {visibleEventCount > PAGE_SIZE ? (
              <div className={styles.pagination}>
                <Pagination
                  current={page}
                  pageSize={PAGE_SIZE}
                  total={visibleEventCount}
                  showSizeChanger={false}
                  onChange={setPage}
                />
              </div>
            ) : null}
          </Card>

          <Text type="secondary" className={styles.scanMeta}>
            最近扫描：{formatDateTime(latestResult.finished_at)} · 共检索{" "}
            {latestResult.provider_request_count} 次 · 发现 {latestResult.raw_result_count}{" "}
            条公开信息 · 整理后保留 {latestResult.unique_result_count} 条
          </Text>
        </>
      ) : activeScan ? null : (
        <Card className={styles.block}>
          <Empty
            description={
              <Space direction="vertical">
                <Text>当前主体还没有负面信息指数结果。</Text>
                <Text type="secondary">
                  首次扫描将从公开网络查找与当前主体相关的信息，并进行风险识别和重复事件整理。
                </Text>
              </Space>
            }
          >
            <Button type="primary" onClick={() => void startScan()} loading={starting}>
              开始首次扫描
            </Button>
          </Empty>
        </Card>
      )}

      <Modal
        open={Boolean(visibleDetail) || visibleDetailLoading}
        title={visibleDetail?.title ?? "负面风险事件"}
        width={880}
        footer={null}
        onCancel={closeDetail}
        destroyOnHidden
      >
        {visibleDetailLoading && !visibleDetail ? (
          <Skeleton active />
        ) : visibleDetail ? (
          <Space direction="vertical" size="middle" className={styles.fullWidth}>
            <Space wrap>
              <Tag>{CATEGORY_LABELS[visibleDetail.category]}</Tag>
              <Tag>{CLAIM_LABELS[visibleDetail.claim_type]}</Tag>
              <Tag>{STATUS_LABELS[visibleDetail.status]}</Tag>
              <Text strong>当前风险 {Math.round(riskNumber(visibleDetail.current_risk))}</Text>
            </Space>
            <Paragraph>{visibleDetail.summary || "暂无事件摘要。"}</Paragraph>
            <Row gutter={[12, 12]}>
              <Col span={6}>
                <Statistic title="严重程度" value={visibleDetail.severity_score} />
              </Col>
              <Col span={6}>
                <Statistic title="证据可信度" value={visibleDetail.evidence_score} />
              </Col>
              <Col span={6}>
                <Statistic title="搜索可见度" value={visibleDetail.visibility_score} />
              </Col>
              <Col span={6}>
                <Statistic title="关联信源" value={visibleDetail.source_count} />
              </Col>
            </Row>
            <Title level={5}>公开证据</Title>
            {visibleDetail.sources.map((source) => (
              <Card size="small" key={source.id}>
                <Space direction="vertical" size={4} className={styles.fullWidth}>
                  <Space wrap>
                    <Text strong>{source.website || source.domain}</Text>
                    <Tag>{CLAIM_LABELS[source.claim_type]}</Tag>
                    {source.verification_status === "succeeded" ? (
                      <Tag color="green">正文已核验</Tag>
                    ) : null}
                    <Text type="secondary">证据可信度 {source.evidence_confidence}</Text>
                  </Space>
                  <Text>{source.title}</Text>
                  <Paragraph type="secondary" ellipsis={{ rows: 3, expandable: true }}>
                    {source.snippet}
                  </Paragraph>
                  {source.verification_excerpt ? (
                    <Paragraph className={styles.excerpt} ellipsis={{ rows: 4, expandable: true }}>
                      核验摘录：{source.verification_excerpt}
                    </Paragraph>
                  ) : null}
                  <Space wrap>
                    <Text type="secondary">{formatDate(source.published_at)}</Text>
                    <Button
                      type="link"
                      size="small"
                      icon={<ExportOutlined />}
                      href={source.original_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      查看原文
                    </Button>
                  </Space>
                </Space>
              </Card>
            ))}
          </Space>
        ) : null}
      </Modal>
    </main>
  );
}
