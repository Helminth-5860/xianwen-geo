"use client";

import {
  Alert,
  Button,
  Card,
  Collapse,
  Image,
  Input,
  List,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useEffect, useRef, useState } from "react";

import { AuthApiError, getCurrentUser, userMessage } from "@/lib/auth-client";
import {
  createPlanApplication,
  getPublicPlans,
  type PlanApplication,
  type PublicPlan,
} from "@/lib/plans-client";
import {
  PLAN_APPLICATION_STATUS_LABELS,
  publicPlanBenefitLines,
  publicPlanCoreBenefitLines,
} from "@/lib/product-copy";
import { getSalesContact, type ResolvedSalesContact } from "@/lib/sales-contact-client";

import styles from "./plan-catalog.module.css";

type PlanCatalogProps = Readonly<{
  currentPlanId?: string | null;
}>;

const CUSTOM_CONTACT_PLAN: PublicPlan = {
  id: "custom-contact",
  code: "custom-contact",
  name: "自定义套餐",
  description: "根据业务规模灵活配置功能额度与服务方案。",
  price_display_mode: "contact",
  display_price: null,
  display_currency: "CNY",
  is_trial: false,
  valid_days: 365,
  benefits: {},
  models: [],
  supports_formal_composite: true,
  sort_order: 999,
  plan_version_id: "custom-contact",
  version_no: 1,
};

function planPrice(plan: PublicPlan) {
  if (plan.price_display_mode === "contact") return "按需定制";
  const price = Number(plan.display_price ?? 0);
  if (price === 0) return "免费";
  return `¥${price.toLocaleString("zh-CN")}`;
}

export function PlanCatalog({ currentPlanId = null }: PlanCatalogProps) {
  const [plans, setPlans] = useState<PublicPlan[] | null>(null);
  const [error, setError] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [selected, setSelected] = useState<PublicPlan | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [application, setApplication] = useState<PlanApplication | null>(null);
  const [submitError, setSubmitError] = useState("");
  const [salesOpen, setSalesOpen] = useState(false);
  const [salesLoading, setSalesLoading] = useState(false);
  const [salesContact, setSalesContact] = useState<ResolvedSalesContact | null>(null);
  const [salesError, setSalesError] = useState("");
  const [qrFailed, setQrFailed] = useState(false);
  const idempotencyKey = useRef("");

  useEffect(() => {
    void getPublicPlans()
      .then(setPlans)
      .catch((reason) => setError(userMessage(reason)));
    void getCurrentUser()
      .then(() => setAuthenticated(true))
      .catch((reason) => {
        if (!(reason instanceof AuthApiError && reason.status === 401)) {
          setError(userMessage(reason));
        }
      });
  }, []);

  const openApplication = (plan: PublicPlan) => {
    setSelected(plan);
    setNote("");
    setApplication(null);
    setSubmitError("");
    idempotencyKey.current = crypto.randomUUID();
  };

  const closeApplication = () => {
    if (submitting) return;
    setSelected(null);
    idempotencyKey.current = "";
  };

  const submit = async () => {
    if (!selected || submitting) return;
    setSubmitting(true);
    setSubmitError("");
    try {
      const result = await createPlanApplication(
        selected.id,
        selected.plan_version_id,
        note,
        idempotencyKey.current,
      );
      setApplication(result);
    } catch (reason) {
      setSubmitError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  const openSalesContact = async () => {
    setSalesOpen(true);
    setSalesLoading(true);
    setSalesContact(null);
    setSalesError("");
    setQrFailed(false);
    try {
      setSalesContact(await getSalesContact());
    } catch (reason) {
      setSalesError(userMessage(reason));
    } finally {
      setSalesLoading(false);
    }
  };

  if (error) return <Alert type="error" title="套餐加载失败" description={error} />;
  if (!plans) return <Spin description="正在加载套餐" />;
  const contactPlan = plans.find((plan) => plan.price_display_mode === "contact");
  const displayPlans = [
    ...plans.filter((plan) => plan.price_display_mode !== "contact"),
    contactPlan ?? CUSTOM_CONTACT_PLAN,
  ];

  return (
    <section aria-labelledby="plans-title" className={styles.catalog}>
      <div className={styles.heading}>
        <Typography.Title level={2} id="plans-title">
          套餐选择与对比
        </Typography.Title>
        <Typography.Paragraph type="secondary">
          根据当前业务规模选择合适套餐，完整权益可在各套餐内展开查看。
        </Typography.Paragraph>
      </div>
      <List
        className={styles.grid}
        grid={{ gutter: 16, xs: 1, sm: 2, lg: 3, xxl: 5 }}
        dataSource={displayPlans}
        renderItem={(plan) => {
          const isCurrent = plan.id === currentPlanId;
          const isContactPlan = plan.price_display_mode === "contact";
          const coreBenefits = isContactPlan
            ? ["按需定制权益", "灵活配置额度"]
            : publicPlanCoreBenefitLines(plan.benefits);
          const allBenefits = publicPlanBenefitLines(plan.benefits);
          const extraBenefits = allBenefits.filter((benefit) => !coreBenefits.includes(benefit));
          const completeBenefits = isContactPlan
            ? ["按需定制权益", "灵活配置额度"]
            : [
                ...extraBenefits,
                plan.supports_formal_composite ? "支持正式综合分" : "不包含正式综合分",
                `可使用 ${plan.models.length} 个 AI 模型`,
              ];
          return (
            <List.Item className={styles.item}>
              <Card
                className={`${styles.card} ${isCurrent ? styles.currentCard : ""}`}
                title={plan.name}
                extra={isCurrent ? <Tag color="blue">当前套餐</Tag> : null}
              >
                <Typography.Paragraph className={styles.description}>
                  {plan.description}
                </Typography.Paragraph>
                <Typography.Title level={3} className={styles.price}>
                  {planPrice(plan)}
                </Typography.Title>
                <Tag>{plan.valid_days === 365 ? "一年有效" : `${plan.valid_days} 天有效`}</Tag>
                <List
                  className={styles.benefits}
                  size="small"
                  dataSource={coreBenefits}
                  locale={{ emptyText: "具体权益由销售人员为你配置。" }}
                  renderItem={(benefit) => <List.Item>✓ {benefit}</List.Item>}
                />
                <Collapse
                  className={styles.collapse}
                  ghost
                  size="small"
                  items={[
                    {
                      key: "all",
                      label: "查看完整权益",
                      children: (
                        <List
                          size="small"
                          dataSource={completeBenefits}
                          locale={{ emptyText: "具体权益以套餐说明为准。" }}
                          renderItem={(benefit) => <List.Item>{benefit}</List.Item>}
                        />
                      ),
                    },
                  ]}
                />
                <div className={styles.action}>
                  {isCurrent ? (
                    <Button block disabled>
                      当前使用
                    </Button>
                  ) : isContactPlan ? (
                    <Button block type="primary" onClick={() => void openSalesContact()}>
                      联系销售
                    </Button>
                  ) : plan.is_trial ? (
                    <Alert type="info" title="请联系工作人员确认体验开通。" />
                  ) : authenticated ? (
                    <Button block type="primary" onClick={() => openApplication(plan)}>
                      选择套餐
                    </Button>
                  ) : (
                    <Button block href="/login?next=%2Fsubscription">
                      登录后选择套餐
                    </Button>
                  )}
                </div>
              </Card>
            </List.Item>
          );
        }}
      />

      <Modal
        title="申请套餐"
        open={selected !== null}
        okText={application ? "已提交" : "确认申请"}
        cancelText="关闭"
        okButtonProps={{ disabled: application !== null }}
        confirmLoading={submitting}
        onOk={() => void submit()}
        onCancel={closeApplication}
      >
        {selected && (
          <Space orientation="vertical" style={{ width: "100%" }}>
            <Typography.Text strong>{selected.name}</Typography.Text>
            <List
              size="small"
              header="套餐包含"
              dataSource={publicPlanBenefitLines(selected.benefits)}
              locale={{ emptyText: "具体内容以套餐说明为准。" }}
              renderItem={(benefit) => <List.Item>{benefit}</List.Item>}
            />
            {!application && (
              <Input.TextArea
                aria-label="申请备注"
                value={note}
                maxLength={500}
                placeholder="选填，请勿填写密码或验证码"
                onChange={(event) => setNote(event.target.value)}
              />
            )}
            {submitError ? <Alert type="error" showIcon title={submitError} /> : null}
            {application && (
              <Alert
                type="success"
                showIcon
                title="申请已提交"
                description={`申请编号：${application.id}，当前状态：${PLAN_APPLICATION_STATUS_LABELS[application.status]}`}
              />
            )}
          </Space>
        )}
      </Modal>

      <Modal
        title="联系销售"
        open={salesOpen}
        footer={<Button onClick={() => setSalesOpen(false)}>关闭</Button>}
        onCancel={() => setSalesOpen(false)}
      >
        <div className={styles.salesContact}>
          {salesLoading ? <Spin description="正在获取销售联系方式" /> : null}
          {!salesLoading && salesError ? (
            <Alert type="warning" showIcon title="销售联系方式暂时无法显示，请稍后再试。" />
          ) : null}
          {!salesLoading && !salesError && salesContact?.configured && salesContact.qr_code_url ? (
            qrFailed ? (
              <Alert type="warning" showIcon title="销售联系方式暂时无法显示，请稍后再试。" />
            ) : (
              <>
                <Image
                  className={styles.qrCode}
                  src={salesContact.qr_code_url}
                  alt="销售微信二维码"
                  preview={false}
                  width={240}
                  onError={() => setQrFailed(true)}
                />
                <Typography.Text>微信扫码联系销售</Typography.Text>
              </>
            )
          ) : null}
          {!salesLoading &&
          !salesError &&
          salesContact &&
          (!salesContact.configured || !salesContact.qr_code_url) ? (
            <Alert
              type="info"
              showIcon
              title={salesContact.message || "销售联系方式暂未配置，请稍后联系平台客服。"}
            />
          ) : null}
        </div>
      </Modal>
    </section>
  );
}
