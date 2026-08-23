"use client";

import {
  ArrowRightOutlined,
  BarChartOutlined,
  BulbOutlined,
  FileTextOutlined,
  RadarChartOutlined,
  SyncOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Button, ConfigProvider, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { getCurrentUser } from "@/lib/auth-client";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";

import styles from "./home.module.css";

const { Paragraph, Text, Title } = Typography;

const workflow = [
  {
    index: "01",
    title: "建立主体",
    description: "沉淀品牌、产品、服务与竞争对手信息，形成持续优化的 GEO 主体。",
    icon: TagsOutlined,
  },
  {
    index: "02",
    title: "构建问题库",
    description: "围绕真实搜索意图组织关键词与用户问题，明确应该被 AI 看见的场景。",
    icon: BulbOutlined,
  },
  {
    index: "03",
    title: "多模型检测",
    description: "在多个主流 AI 模型中检测品牌提及、推荐位置、引用与竞争表现。",
    icon: RadarChartOutlined,
  },
  {
    index: "04",
    title: "诊断与评分",
    description: "把分散结果聚合成 GEO 报告，定位可见度缺口与优先优化方向。",
    icon: BarChartOutlined,
  },
  {
    index: "05",
    title: "执行优化",
    description: "从策略直接进入文章、FAQ 与内容建设，让优化动作与检测问题对应。",
    icon: FileTextOutlined,
  },
  {
    index: "06",
    title: "持续复测",
    description: "优化后再次检测，追踪品牌在 AI 搜索与推荐结果中的真实变化。",
    icon: SyncOutlined,
  },
];

const models = ["DeepSeek", "豆包", "通义千问", "腾讯混元", "百度文心", "Kimi", "智谱 GLM", "讯飞星火"];

export default function Home() {
  const router = useRouter();

  useEffect(() => {
    let current = true;
    void getCurrentUser()
      .then((user) => {
        if (current) router.replace(user.home_route);
      })
      .catch(() => undefined);
    return () => {
      current = false;
    };
  }, [router]);

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1268e8", borderRadius: 12 } }}>
      <main className={styles.page}>
        <header className={styles.header}>
          <a className={styles.brand} href="/" aria-label="显问 GEO 首页">
            <span className={styles.brandMark}>显问</span>
            <span className={styles.brandMeta}>GEO</span>
          </a>
          <nav className={styles.headerActions} aria-label="访客导航">
            <Button type="text" href="/login">
              登录
            </Button>
            <Button type="primary" href="/register">
              开始使用
            </Button>
          </nav>
        </header>

        <section className={styles.hero}>
          <div className={styles.heroCopy}>
            <Text className={styles.eyebrow}>GENERATIVE ENGINE OPTIMIZATION</Text>
            <Title className={styles.heroTitle}>看见品牌在 AI 搜索里的真实可见度</Title>
            <Paragraph className={styles.heroDescription}>{SITE_DESCRIPTION}</Paragraph>
            <div className={styles.heroActions}>
              <Button type="primary" size="large" href="/register" icon={<ArrowRightOutlined />} iconPosition="end">
                创建 GEO 主体
              </Button>
              <Button size="large" href="/login">
                登录工作台
              </Button>
            </div>
            <div className={styles.modelLine}>
              <span>覆盖主流 AI 模型</span>
              <div className={styles.modelList}>
                {models.map((model) => (
                  <span key={model}>{model}</span>
                ))}
              </div>
            </div>
          </div>

          <div className={styles.heroPanel} aria-label="GEO 优化闭环示意">
            <div className={styles.panelHeader}>
              <div>
                <span className={styles.panelEyebrow}>GEO WORKFLOW</span>
                <strong>从检测到复测的一条主线</strong>
              </div>
              <span className={styles.liveDot}>持续优化</span>
            </div>
            <div className={styles.panelScore}>
              <div>
                <span>品牌可见度</span>
                <strong>检测 · 洞察 · 优化</strong>
              </div>
              <RadarChartOutlined />
            </div>
            <div className={styles.panelSteps}>
              {workflow.slice(0, 4).map((item) => (
                <div className={styles.panelStep} key={item.index}>
                  <span>{item.index}</span>
                  <strong>{item.title}</strong>
                </div>
              ))}
            </div>
            <div className={styles.panelFooter}>每一次内容优化，都能回到下一次 AI 检测中验证。</div>
          </div>
        </section>

        <section className={styles.workflowSection} id="workflow">
          <div className={styles.sectionHeading}>
            <Text className={styles.eyebrow}>GEO 主线流程</Text>
            <Title level={2}>不是一堆 AI 工具，而是一条可执行的优化闭环</Title>
            <Paragraph>
              显问围绕同一个品牌主体，把问题库、AI 检测、评分诊断、改善策略、内容执行和持续复测连接起来。
            </Paragraph>
          </div>

          <div className={styles.workflowGrid}>
            {workflow.map((item) => {
              const Icon = item.icon;
              return (
                <article className={styles.workflowCard} key={item.index}>
                  <div className={styles.workflowCardTop}>
                    <span>{item.index}</span>
                    <Icon />
                  </div>
                  <Title level={3}>{item.title}</Title>
                  <Paragraph>{item.description}</Paragraph>
                </article>
              );
            })}
          </div>
        </section>

        <section className={styles.focusSection}>
          <div className={styles.focusCopy}>
            <Text className={styles.eyebrow}>面向企业 GEO 运营</Text>
            <Title level={2}>先知道 AI 为什么没有推荐你，再决定该做什么</Title>
          </div>
          <div className={styles.focusList}>
            <div>
              <strong>AI 可见度</strong>
              <span>品牌是否被提及、推荐，以及在不同模型中的表现差异。</span>
            </div>
            <div>
              <strong>竞争与引用</strong>
              <span>竞争对手出现在哪里，AI 的回答更倾向引用哪些内容与来源。</span>
            </div>
            <div>
              <strong>优化动作</strong>
              <span>把检测缺口转成明确策略与内容任务，并持续通过复测验证效果。</span>
            </div>
          </div>
        </section>

        <section className={styles.cta}>
          <div>
            <Text className={styles.eyebrow}>开始建立你的 GEO 基线</Text>
            <Title level={2}>{SITE_NAME}</Title>
            <Paragraph>创建主体，建立问题库，然后开始第一次 AI 可见度检测。</Paragraph>
          </div>
          <div className={styles.ctaActions}>
            <Button type="primary" size="large" href="/register">
              开始使用
            </Button>
            <Button size="large" href="/login">
              已有账号，登录
            </Button>
          </div>
        </section>

        <footer className={styles.footer}>
          <span>显问 GEO · xianwenai.cn</span>
          <span>让 GEO 优化有检测、有执行，也有验证。</span>
        </footer>
      </main>
    </ConfigProvider>
  );
}
