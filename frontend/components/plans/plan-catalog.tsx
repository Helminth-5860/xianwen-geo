"use client";

import {
  Alert,
  Button,
  Card,
  Collapse,
  Empty,
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

export function PlanCatalog() {
  const [plans, setPlans] = useState<PublicPlan[] | null>(null);
  const [error, setError] = useState("");
  const [authenticated, setAuthenticated] = useState(false);
  const [selected, setSelected] = useState<PublicPlan | null>(null);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [application, setApplication] = useState<PlanApplication | null>(null);
  const [submitError, setSubmitError] = useState("");
  const idempotencyKey = useRef("");
  useEffect(() => {
    void getPublicPlans()
      .then(setPlans)
      .catch((reason) => setError(userMessage(reason)));
    void getCurrentUser()
      .then(() => setAuthenticated(true))
      .catch((reason) => {
        if (!(reason instanceof AuthApiError && reason.status === 401))
          setError(userMessage(reason));
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
  if (error) return <Alert type="error" message="套餐加载失败" description={error} />;
  if (!plans) return <Spin description="正在加载套餐" />;
  if (!plans.length) {
    return <Empty description="当前没有可申请的套餐，请稍后查看或联系管理员。" />;
  }
  return (
    <section aria-labelledby="plans-title">
      <Typography.Title level={2} id="plans-title">
        可用套餐
      </Typography.Title>
      <List
        grid={{ gutter: 16, xs: 1, md: 2, xl: 4 }}
        dataSource={plans}
        renderItem={(plan) => {
          const recommended = plan.is_recommended ?? plan.code === "professional-6980";
          const coreBenefits = publicPlanCoreBenefitLines(plan.benefits);
          const allBenefits = publicPlanBenefitLines(plan.benefits);
          const extraBenefits = allBenefits.filter((benefit) => !coreBenefits.includes(benefit));
          return (
            <List.Item>
              <Card
                title={plan.name}
                extra={recommended ? <Tag color="purple">推荐</Tag> : null}
                style={
                  recommended
                    ? { borderColor: "#7c5cff", boxShadow: "0 12px 30px #7257ff1f" }
                    : undefined
                }
              >
                <Typography.Paragraph>{plan.description}</Typography.Paragraph>
                <Typography.Title level={3}>
                  {plan.price_display_mode === "fixed" ? `¥${plan.display_price}` : "联系开通"}
                </Typography.Title>
                <Space wrap>
                  <Tag>{plan.valid_days === 365 ? "一年有效" : `${plan.valid_days} 天有效`}</Tag>
                  <Tag color={plan.supports_formal_composite ? "green" : "orange"}>
                    {plan.supports_formal_composite ? "支持正式综合分" : "不支持正式综合分"}
                  </Tag>
                </Space>
                {plan.is_trial ? (
                  <Typography.Paragraph strong style={{ marginTop: 16 }}>
                    完整体验核心流程
                  </Typography.Paragraph>
                ) : null}
                <List
                  size="small"
                  dataSource={coreBenefits}
                  locale={{ emptyText: "具体权益以完整说明为准。" }}
                  renderItem={(benefit) => <List.Item>✓ {benefit}</List.Item>}
                />
                <Collapse
                  ghost
                  size="small"
                  items={[
                    {
                      key: "all",
                      label: "查看完整权益",
                      children: (
                        <List
                          size="small"
                          dataSource={[...extraBenefits, `可使用 ${plan.models.length} 个 AI 模型`]}
                          locale={{ emptyText: "具体权益以套餐说明为准。" }}
                          renderItem={(benefit) => <List.Item>{benefit}</List.Item>}
                        />
                      ),
                    },
                  ]}
                />
                {plan.is_trial ? (
                  <Alert type="info" message="提交申请后，我们会联系你确认试用开通事宜。" />
                ) : authenticated ? (
                  <Button type="primary" onClick={() => openApplication(plan)}>
                    申请开通
                  </Button>
                ) : (
                  <Button href="/login?next=%2F">登录后申请套餐</Button>
                )}
                <Typography.Paragraph type="secondary">
                  提交后，工作人员会联系你确认套餐和开通时间。
                </Typography.Paragraph>
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
          <Space direction="vertical" style={{ width: "100%" }}>
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
            {submitError && <Alert type="error" showIcon message={submitError} />}
            {application && (
              <Alert
                type="success"
                showIcon
                message="申请已提交"
                description={`申请编号：${application.id}，当前状态：${PLAN_APPLICATION_STATUS_LABELS[application.status]}`}
              />
            )}
          </Space>
        )}
      </Modal>
    </section>
  );
}
