"use client";

import {
  ApiOutlined,
  CheckCircleFilled,
  CloudServerOutlined,
  CompassOutlined,
  FileTextOutlined,
  FundViewOutlined,
  PictureOutlined,
  RobotOutlined,
  TagsOutlined,
} from "@ant-design/icons";
import { Alert, Button, Card, ConfigProvider, Space, Spin, Tag, Typography } from "antd";
import zhCN from "antd/locale/zh_CN";
import { useEffect, useState, useSyncExternalStore } from "react";

import { PlanCatalog } from "@/components/plans/plan-catalog";
import { AuthApiError, getCurrentUser, type AccountUser } from "@/lib/auth-client";
import { publicEnvironment } from "@/lib/env";
import { getCurrentSubscription, type Subscription } from "@/lib/plans-client";
import { SITE_DESCRIPTION, SITE_NAME } from "@/lib/site";

const { Paragraph, Text, Title } = Typography;

export default function Home() {
  const [user, setUser] = useState<AccountUser | null | undefined>();
  const [subscription, setSubscription] = useState<Subscription | null | undefined>();
  const [workspaceError, setWorkspaceError] = useState("");
  const pendingAccount = useSyncExternalStore(
    () => () => undefined,
    () => new URLSearchParams(window.location.search).get("account") === "pending",
    () => false,
  );

  useEffect(() => {
    let current = true;
    void getCurrentUser()
      .then(async (value) => {
        if (!current) return;
        setUser(value);
        try {
          const data = await getCurrentSubscription();
          if (current) setSubscription(data.current);
        } catch (reason) {
          if (current) {
            setWorkspaceError(reason instanceof Error ? reason.message : "工作台加载失败");
          }
        }
      })
      .catch((reason) => {
        if (!current) return;
        if (reason instanceof AuthApiError && reason.status !== 401) {
          setWorkspaceError(reason.message);
        }
        setUser(null);
      });
    return () => {
      current = false;
    };
  }, []);

  const authenticated = user !== null && user !== undefined;

  return (
    <ConfigProvider locale={zhCN} theme={{ token: { colorPrimary: "#1668dc", borderRadius: 12 } }}>
      <main className="page-shell">
        {pendingAccount && (
          <Alert
            className="account-status-alert"
            type="info"
            showIcon
            title="账号待审核"
            description="你已成功登录。审核通过前可以查看系统说明，后续主体资料功能将按任务逐步开放。"
          />
        )}
        <section className="hero">
          <Tag color="blue" icon={<CheckCircleFilled />}>
            {authenticated ? "用户工作台已就绪" : "账号与认证基础已就绪"}
          </Tag>
          <Title>{authenticated ? `${user.nickname}，欢迎回来` : SITE_NAME}</Title>
          <Paragraph className="hero-description">
            {authenticated
              ? "即使尚未开通套餐，也可以进入工作台、创建一个主体草稿并了解完整功能；体验额度和正式套餐只控制实际用量。"
              : SITE_DESCRIPTION}
          </Paragraph>
          <Space wrap>
            {authenticated ? (
              <>
                <Button type="primary" href="/subjects">
                  进入主体工作台
                </Button>
                <Button href="/assistant">打开 AI 助手</Button>
                <Button href="/subscription">查看订阅与额度</Button>
              </>
            ) : (
              <>
                <Button type="primary" href="/register">
                  创建账号
                </Button>
                <Button href="/login">登录</Button>
                <Button href="/api/health">检查前端状态</Button>
                <Button href={`${publicEnvironment.apiBaseUrl}/health/`}>检查后端状态</Button>
              </>
            )}
          </Space>
        </section>

        {user === undefined ? (
          <Spin description="正在加载工作台" />
        ) : authenticated ? (
          <>
            {workspaceError && <Alert type="error" showIcon title={workspaceError} />}
            {!workspaceError && subscription === undefined && (
              <Spin description="正在加载订阅状态" />
            )}
            {!workspaceError && subscription === null && (
              <Alert
                className="workspace-entitlement-alert"
                type="info"
                showIcon
                title="当前没有生效套餐，但工作台功能仍然可见"
                description="你可以先创建并完善一个主体草稿。开通免费体验或正式套餐后，即可激活主体并使用需要额度的检测、内容和图片能力。"
                action={<Button href="#plans-title">查看体验与正式套餐</Button>}
              />
            )}
            {subscription && (
              <Alert
                className="workspace-entitlement-alert"
                type="success"
                showIcon
                title={`${subscription.plan_name}已生效`}
                description={subscription.is_trial ? "当前为免费体验套餐。" : "当前为正式套餐。"}
                action={<Button href="/subscription">查看权益</Button>}
              />
            )}
            <section className="workspace-grid" aria-label="用户功能工作台">
              <Card>
                <CompassOutlined className="card-icon" />
                <Title level={3}>主体资料</Title>
                <Text>无套餐也能创建并完善一个主体草稿；体验或正式套餐用于激活主体。</Text>
                <Button type="link" href="/subjects">
                  进入主体工作台
                </Button>
              </Card>
              <Card>
                <TagsOutlined className="card-icon" />
                <Title level={3}>关键词与问题库</Title>
                <Text>围绕主体生成、蒸馏和维护关键词与用户真实提问，形成检测输入。</Text>
                <Button type="link" href="/subjects">
                  选择主体开始
                </Button>
              </Card>
              <Card>
                <FundViewOutlined className="card-icon" />
                <Title level={3}>GEO 检测与报告</Title>
                <Text>执行多模型 GEO 检测，查看曝光、竞品引用、评分和历史报告。</Text>
                <Button type="link" href="/subjects">
                  进入检测流程
                </Button>
              </Card>
              <Card>
                <PictureOutlined className="card-icon" />
                <Title level={3}>改善策略与内容</Title>
                <Text>从检测报告生成改善策略、文章、大纲和图片，并完成发布准备。</Text>
                <Button type="link" href="/subjects">
                  查看内容工作流
                </Button>
              </Card>
              <Card>
                <RobotOutlined className="card-icon" />
                <Title level={3}>显问 AI 助手</Title>
                <Text>围绕当前主体、检测报告和改善策略进行安全问答。</Text>
                <Button type="link" href="/assistant">
                  打开 AI 助手
                </Button>
              </Card>
              <Card>
                <FileTextOutlined className="card-icon" />
                <Title level={3}>套餐与额度</Title>
                <Text>查看免费体验、当前订阅和套餐申请进度，按需升级正式权益。</Text>
                <Space wrap>
                  <Button type="link" href="/subscription">
                    我的订阅
                  </Button>
                  <Button type="link" href="/plan-applications">
                    申请记录
                  </Button>
                </Space>
              </Card>
            </section>
          </>
        ) : (
          <section className="status-grid" aria-label="工程组件">
            <Card>
              <ApiOutlined className="card-icon" />
              <Title level={3}>安全认证</Title>
              <Text>支持密码和短信验证码登录，使用 HttpOnly Session 与真实 CSRF 防护。</Text>
            </Card>
            <Card>
              <CloudServerOutlined className="card-icon" />
              <Title level={3}>后端</Title>
              <Text>Django、DRF 与 Celery 已具备统一错误、日志和任务队列基础。</Text>
            </Card>
            <Card>
              <CheckCircleFilled className="card-icon" />
              <Title level={3}>基础设施</Title>
              <Text>Docker Compose 统一编排 PostgreSQL、Redis 和应用服务。</Text>
            </Card>
          </section>
        )}

        <PlanCatalog />
      </main>
    </ConfigProvider>
  );
}
