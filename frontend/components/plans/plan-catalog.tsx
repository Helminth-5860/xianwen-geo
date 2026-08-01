"use client";

import { Alert, Button, Card, Empty, Input, List, Modal, Space, Spin, Tag, Typography } from "antd";
import { useEffect, useRef, useState } from "react";
import { AuthApiError, getCurrentUser, userMessage } from "@/lib/auth-client";
import {
  createPlanApplication,
  getPublicPlans,
  type PlanApplication,
  type PublicPlan,
} from "@/lib/plans-client";

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
  if (!plans.length) return <Empty description="当前暂无可用套餐" />;
  return (
    <section aria-labelledby="plans-title">
      <Typography.Title level={2} id="plans-title">
        可用套餐
      </Typography.Title>
      <List
        grid={{ gutter: 16, xs: 1, md: 2, lg: 3 }}
        dataSource={plans}
        renderItem={(plan) => (
          <List.Item>
            <Card title={plan.name}>
              <Typography.Paragraph>{plan.description}</Typography.Paragraph>
              <Typography.Title level={3}>
                {plan.price_display_mode === "fixed" ? `¥${plan.display_price}` : "联系开通"}
              </Typography.Title>
              <Space wrap>
                <Tag>{plan.valid_days} 天</Tag>
                <Tag color={plan.supports_formal_composite ? "green" : "orange"}>
                  {plan.supports_formal_composite ? "支持正式综合分" : "不支持正式综合分"}
                </Tag>
              </Space>
              <Typography.Paragraph>
                模型：{plan.models.map((item) => item.name).join("、")}
              </Typography.Paragraph>
              {plan.is_trial ? (
                <Alert type="info" message="试用由管理员审核后发放" />
              ) : authenticated ? (
                <Button type="primary" onClick={() => openApplication(plan)}>
                  申请套餐 / 联系开通
                </Button>
              ) : (
                <Button href="/login?next=%2F">登录后申请套餐</Button>
              )}
              <Typography.Paragraph type="secondary">
                不提供在线购买，不会创建申请或订单。
              </Typography.Paragraph>
            </Card>
          </List.Item>
        )}
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
            <Typography.Text strong>
              {selected.name} · 第 {selected.version_no} 版
            </Typography.Text>
            <Typography.Paragraph>
              权益摘要：{Object.keys(selected.benefits).join("、") || "以套餐公开说明为准"}
            </Typography.Paragraph>
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
                description={`申请编号：${application.id}，状态：${application.status}`}
              />
            )}
          </Space>
        )}
      </Modal>
    </section>
  );
}
