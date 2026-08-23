"use client";

import {
  ArrowRightOutlined,
  CheckCircleFilled,
  ClockCircleOutlined,
  FileSearchOutlined,
  FileTextOutlined,
  FundProjectionScreenOutlined,
  RadarChartOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, ConfigProvider, Empty, Space, Spin, Tag, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import { getCurrentUser, userMessage, type AccountUser } from "@/lib/auth-client";
import { getReportHistory, type GeoReport } from "@/lib/geo-report-client";
import { getQuestionBankDraft, type QuestionBankDraft } from "@/lib/question-bank-client";
import { getSubjects, type SubjectSummary } from "@/lib/subjects-client";

const { Paragraph, Text, Title } = Typography;

type WorkflowItem = Readonly<{
  title: string;
  description: string;
  status: string;
  href: string;
  icon: typeof TagsOutlined;
  tone: "done" | "ready" | "waiting" | "attention";
}>;

const metricValue = (value: string | null | undefined) => value ?? "—";

export default function WorkspacePage() {
  const router = useRouter();
  const [user, setUser] = useState<AccountUser | null>();
  const [subjects, setSubjects] = useState<SubjectSummary[]>([]);
  const [currentSubject, setCurrentSubject] = useState<SubjectSummary | null>(null);
  const [questionBank, setQuestionBank] = useState<QuestionBankDraft | null>(null);
  const [reports, setReports] = useState<GeoReport[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let current = true;

    void getCurrentUser()
      .then(async (account) => {
        if (!current) return;
        setUser(account);
        const subjectData = await getSubjects();
        if (!current) return;
        setSubjects(subjectData.subjects);
        const subject =
          subjectData.subjects.find((item) => item.id === subjectData.context.current_subject_id) ??
          subjectData.subjects.find((item) => item.is_current) ??
          null;
        setCurrentSubject(subject);

        if (!subject) return;

        const [reportResult, questionResult] = await Promise.allSettled([
          getReportHistory(subject.id),
          getQuestionBankDraft(subject.id),
        ]);
        if (!current) return;

        if (reportResult.status === "fulfilled") {
          setReports(
            [...reportResult.value.items].sort(
              (left, right) =>
                new Date(right.generated_at).getTime() - new Date(left.generated_at).getTime(),
            ),
          );
        }
        if (questionResult.status === "fulfilled") setQuestionBank(questionResult.value);
      })
      .catch((reason) => {
        if (!current) return;
        setUser(null);
        if (reason && typeof reason === "object" && "status" in reason && reason.status === 401) {
          router.replace("/login");
          return;
        }
        setError(userMessage(reason));
      })
      .finally(() => {
        if (current) setLoading(false);
      });

    return () => {
      current = false;
    };
  }, [router]);

  const latestReport = reports[0] ?? null;
  const subjectName = currentSubject?.official_name || currentSubject?.subject_type.name || "当前主体";
  const questionReady = Boolean(questionBank?.current_question_bank_version_no);

  const workflow = useMemo<WorkflowItem[]>(() => {
    if (!currentSubject) return [];

    const subjectReady = currentSubject.current_version_no !== null;
    return [
      {
        title: "1. 主体与知识",
        description: "完善品牌、产品、资料和公开来源，建立 GEO 的事实基础。",
        status: subjectReady ? `正式版本 v${currentSubject.current_version_no}` : "待提交正式版本",
        href: `/subjects/${currentSubject.id}`,
        icon: CheckCircleFilled,
        tone: subjectReady ? "done" : "attention",
      },
      {
        title: "2. 关键词与问题",
        description: "形成关键词、蒸馏结果和用户真实问题库，作为检测输入。",
        status: questionReady ? `问题库 v${questionBank?.current_question_bank_version_no}` : "待完成问题库",
        href: `/subjects/${currentSubject.id}/keywords`,
        icon: TagsOutlined,
        tone: questionReady ? "done" : subjectReady ? "ready" : "waiting",
      },
      {
        title: "3. AI 可见度检测",
        description: "选择目标问题与 AI 模型，执行真实 GEO 检测。",
        status: latestReport ? "已有检测结果" : questionReady ? "可以开始首次检测" : "等待问题库",
        href: "/geo/detections",
        icon: RadarChartOutlined,
        tone: latestReport ? "done" : questionReady ? "ready" : "waiting",
      },
      {
        title: "4. GEO 报告与洞察",
        description: "查看 GEO Score、曝光、提及、推荐、模型表现和竞争结果。",
        status: latestReport ? "最新报告可查看" : "等待检测结果",
        href: latestReport ? `/geo/reports/${latestReport.id}` : "/geo/reports",
        icon: FileSearchOutlined,
        tone: latestReport ? "ready" : "waiting",
      },
      {
        title: "5. 优化策略",
        description: "基于真实检测报告生成优先级、行动计划和内容选题。",
        status: latestReport ? "可生成或查看策略" : "等待 GEO 报告",
        href: "/geo/strategy",
        icon: FundProjectionScreenOutlined,
        tone: latestReport ? "ready" : "waiting",
      },
      {
        title: "6. 内容执行",
        description: "把 GEO 策略转成文章、渠道稿和内容资产，完成优化落地。",
        status: latestReport ? "可进入内容工作台" : "建议先完成检测与策略",
        href: `/subjects/${currentSubject.id}/articles/new`,
        icon: FileTextOutlined,
        tone: latestReport ? "ready" : "waiting",
      },
      {
        title: "7. 复测验证",
        description: "内容与主体发生变化后重新检测，验证 GEO 指标是否真实提升。",
        status: currentSubject.retest_required ? "主体变更，建议复测" : latestReport ? "可按需复测" : "等待首次检测",
        href: latestReport ? `/geo/reports/${latestReport.id}` : "/geo/detections",
        icon: ClockCircleOutlined,
        tone: currentSubject.retest_required ? "attention" : latestReport ? "ready" : "waiting",
      },
    ];
  }, [currentSubject, latestReport, questionBank?.current_question_bank_version_no, questionReady]);

  const primaryAction = useMemo(() => {
    if (!currentSubject) return { label: "创建主体", href: "/subjects" };
    if (currentSubject.current_version_no === null)
      return { label: "完善主体资料", href: `/subjects/${currentSubject.id}` };
    if (!questionReady)
      return { label: "建立关键词与问题库", href: `/subjects/${currentSubject.id}/keywords` };
    if (!latestReport) return { label: "开始 AI 可见度检测", href: "/geo/detections" };
    if (currentSubject.retest_required)
      return { label: "查看报告并准备复测", href: `/geo/reports/${latestReport.id}` };
    return { label: "查看 GEO 报告", href: `/geo/reports/${latestReport.id}` };
  }, [currentSubject, latestReport, questionReady]);

  if (loading) return <Spin fullscreen description="正在加载 GEO 总览" />;
  if (!user) return null;

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1668dc", borderRadius: 10 } }}>
      <main className="geo-dashboard">
        <section className="geo-dashboard__header">
          <div>
            <Text type="secondary">GEO WORKSPACE</Text>
            <Title level={2}>GEO 总览</Title>
            <Paragraph type="secondary">
              围绕主体、检测、洞察、优化和复测持续推进，不再从一组独立工具中反复选择入口。
            </Paragraph>
          </div>
          <Space wrap>
            <Button href="/subjects">切换主体</Button>
            <Button type="primary" href={primaryAction.href}>
              {primaryAction.label} <ArrowRightOutlined />
            </Button>
          </Space>
        </section>

        {error && <Alert type="error" showIcon message={error} />}

        {!currentSubject ? (
          <Card className="geo-dashboard__empty">
            <Empty
              description={
                <Space direction="vertical" size={4}>
                  <Text strong>还没有当前 GEO 主体</Text>
                  <Text type="secondary">先建立品牌或企业主体，后续关键词、检测、报告和内容都会自动围绕该主体展开。</Text>
                </Space>
              }
            >
              <Button type="primary" href="/subjects">
                创建并选择主体
              </Button>
            </Empty>
          </Card>
        ) : (
          <>
            <section className="geo-dashboard__subject-bar">
              <div>
                <Text type="secondary">当前主体</Text>
                <Title level={3}>{subjectName}</Title>
              </div>
              <Space wrap>
                <Tag color={currentSubject.status === "active" ? "green" : "default"}>
                  {currentSubject.status === "active" ? "已激活" : currentSubject.status === "draft" ? "草稿" : "已归档"}
                </Tag>
                {currentSubject.current_version_no !== null && <Tag>主体 v{currentSubject.current_version_no}</Tag>}
                {currentSubject.retest_required && <Tag color="orange">需要复测</Tag>}
              </Space>
            </section>

            <section className="geo-metric-grid" aria-label="GEO 核心指标">
              <Card>
                <Text type="secondary">GEO Score</Text>
                <div className="geo-metric-grid__value">{metricValue(latestReport?.summary.geo.score)}</div>
                <Text type="secondary">{latestReport ? `等级 ${latestReport.summary.geo.grade || "—"}` : "尚未完成首次检测"}</Text>
              </Card>
              <Card>
                <Text type="secondary">AI 曝光指数</Text>
                <div className="geo-metric-grid__value">{metricValue(latestReport?.summary.exposure.exposure_index)}</div>
                <Text type="secondary">跨模型综合曝光表现</Text>
              </Card>
              <Card>
                <Text type="secondary">品牌提及</Text>
                <div className="geo-metric-grid__value">{metricValue(latestReport?.summary.exposure.mention_rate_score)}</div>
                <Text type="secondary">AI 回答中的品牌出现表现</Text>
              </Card>
              <Card>
                <Text type="secondary">推荐表现</Text>
                <div className="geo-metric-grid__value">{metricValue(latestReport?.summary.exposure.recommendation_rate_score)}</div>
                <Text type="secondary">AI 回答中的推荐倾向表现</Text>
              </Card>
            </section>

            <section className="geo-dashboard__main-grid">
              <Card title="GEO 优化主线" className="geo-workflow-card">
                <div className="geo-workflow-list">
                  {workflow.map((item) => {
                    const Icon = item.icon;
                    return (
                      <a key={item.title} href={item.href} className={`geo-workflow-item geo-workflow-item--${item.tone}`}>
                        <span className="geo-workflow-item__icon"><Icon /></span>
                        <span className="geo-workflow-item__content">
                          <Text strong>{item.title}</Text>
                          <Text type="secondary">{item.description}</Text>
                        </span>
                        <span className="geo-workflow-item__status">{item.status}</span>
                        <ArrowRightOutlined />
                      </a>
                    );
                  })}
                </div>
              </Card>

              <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                <Card title="当前优先事项">
                  {currentSubject.retest_required ? (
                    <Alert type="warning" showIcon message="主体资料已变化" description="现有检测结果可能已经不能完整代表当前主体，建议查看最新报告后安排复测。" />
                  ) : !questionReady ? (
                    <Alert type="info" showIcon message="先完成关键词与问题库" description="GEO 检测必须基于正式的问题库版本，先把用户真实问题确定下来。" />
                  ) : !latestReport ? (
                    <Alert type="info" showIcon message="可以开始首次 GEO 检测" description="问题库已具备，可以选择模型并执行 AI 可见度检测。" />
                  ) : (
                    <Alert type="success" showIcon message="已有 GEO 基线" description="继续查看报告、生成优化策略并执行内容；完成后再用复测验证变化。" />
                  )}
                  <Button type="primary" href={primaryAction.href} style={{ marginTop: 16 }}>
                    {primaryAction.label}
                  </Button>
                </Card>

                <Card title="最近 GEO 报告">
                  {reports.length === 0 ? (
                    <Text type="secondary">暂无检测报告。完成首次 AI 可见度检测后，这里会显示真实 GEO 数据。</Text>
                  ) : (
                    <Space direction="vertical" size="middle" style={{ width: "100%" }}>
                      {reports.slice(0, 4).map((report) => (
                        <a key={report.id} href={`/geo/reports/${report.id}`} className="geo-report-row">
                          <span>
                            <Text strong>GEO Score {metricValue(report.summary.geo.score)}</Text>
                            <Text type="secondary">{new Date(report.generated_at).toLocaleString("zh-CN")}</Text>
                          </span>
                          <ArrowRightOutlined />
                        </a>
                      ))}
                      <Button href="/geo/reports" block>查看全部报告</Button>
                    </Space>
                  )}
                </Card>
              </Space>
            </section>
          </>
        )}

        {subjects.length > 1 && (
          <Text type="secondary" className="geo-dashboard__subject-count">
            当前账号共有 {subjects.length} 个主体，可在“主体与知识”中切换当前 GEO 主体。
          </Text>
        )}
      </main>
    </ConfigProvider>
  );
}
