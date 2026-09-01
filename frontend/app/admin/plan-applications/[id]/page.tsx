"use client";

import {
  Alert,
  Button,
  Card,
  Checkbox,
  Collapse,
  Descriptions,
  Form,
  Input,
  Modal,
  Space,
  Spin,
  Tag,
  Typography,
} from "antd";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";

import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { RiskActionButton } from "@/components/admin/risk-action-button";
import { userMessage } from "@/lib/auth-client";
import {
  changeAdminPlanApplication,
  getAdminPlanApplication,
  type AdminPlanApplication,
  openSubscriptionFromApplication,
} from "@/lib/plans-client";
import { getRiskActions, type RiskMode } from "@/lib/risk-client";

export default function AdminPlanApplicationDetailPage() {
  const { id } = useParams<{ id: string }>();
  const capabilities = useAdminCapabilities();
  const [item, setItem] = useState<AdminPlanApplication | null>(null);
  const [modes, setModes] = useState<Record<string, RiskMode>>({});
  const [activateOpen, setActivateOpen] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [unavailableReason, setUnavailableReason] = useState("");
  const [overrideVersion, setOverrideVersion] = useState("");
  const [overrideConfirmed, setOverrideConfirmed] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [openingNote, setOpeningNote] = useState("");
  const [loadingError, setLoadingError] = useState("");
  const [actionError, setActionError] = useState("");
  const [activating, setActivating] = useState(false);
  useEffect(() => {
    void Promise.all([getAdminPlanApplication(id), getRiskActions()])
      .then(([application, actions]) => {
        setItem(application);
        setModes(Object.fromEntries(actions.map((action) => [action.key, action.current_mode])));
      })
      .catch((reason) => setLoadingError(userMessage(reason)));
  }, [id]);
  if (loadingError) return <Alert type="error" showIcon title={loadingError} />;
  if (!item) return <Spin description="正在加载套餐申请" />;
  const canContact = capabilities?.permission_keys.includes("plan_applications.contact") ?? false;
  const canClose = capabilities?.permission_keys.includes("plan_applications.close") ?? false;
  const canOpen = capabilities?.permission_keys.includes("subscriptions.open") ?? false;
  const canOverride =
    capabilities?.permission_keys.includes("subscriptions.override_version") ?? false;
  return (
    <main className="admin-page">
      <Typography.Title>套餐申请详情</Typography.Title>
      {!canContact && !canClose && (
        <Alert type="info" showIcon title="当前账号没有处理此申请的权限" />
      )}
      <Card>
        <Descriptions column={1}>
          <Descriptions.Item label="申请编号">{item.id}</Descriptions.Item>
          <Descriptions.Item label="用户">{item.applicant_nickname}</Descriptions.Item>
          <Descriptions.Item label="联系电话">{item.applicant_phone}</Descriptions.Item>
          <Descriptions.Item label="绑定版本">第 {item.requested_version_no} 版</Descriptions.Item>
          <Descriptions.Item label="公开快照">
            {String(item.public_plan_snapshot.name)}
          </Descriptions.Item>
          <Descriptions.Item label="当前负责人">
            {item.current_owner?.nickname ?? "未分配"}
          </Descriptions.Item>
          <Descriptions.Item label="状态">
            <Tag>{item.status}</Tag>
          </Descriptions.Item>
        </Descriptions>
        <Space>
          {canContact && item.status === "pending" && (
            <RiskActionButton
              actionName="标记已联系"
              mode={modes["plan_application.contact"] ?? "confirm"}
              execute={(credentials) =>
                changeAdminPlanApplication(item.id, "contact", item.version, credentials)
              }
              onExecuted={setItem}
            >
              标记已联系
            </RiskActionButton>
          )}
          {canClose && (item.status === "pending" || item.status === "contacted") && (
            <RiskActionButton
              actionName="关闭申请"
              danger
              mode={modes["plan_application.close"] ?? "confirm"}
              execute={(credentials) =>
                changeAdminPlanApplication(item.id, "close", item.version, credentials)
              }
              onExecuted={setItem}
            >
              关闭申请
            </RiskActionButton>
          )}
          {canOpen && (item.status === "pending" || item.status === "contacted") && (
            <Button
              type="primary"
              onClick={() => {
                setActionError("");
                setActivateOpen(true);
              }}
            >
              开通订阅
            </Button>
          )}
        </Space>
      </Card>
      <Modal
        title="确认开通订阅"
        open={activateOpen}
        confirmLoading={activating}
        onCancel={() => {
          setActionError("");
          setActivateOpen(false);
        }}
        onOk={async () => {
          if (unavailable && !unavailableReason.trim()) {
            setActionError("请填写特殊状态开通原因。");
            return;
          }
          if (overrideVersion.trim() && (!overrideConfirmed || !overrideReason.trim())) {
            setActionError("更换申请版本时，请确认操作并填写原因。");
            return;
          }
          setActivating(true);
          setActionError("");
          try {
            await openSubscriptionFromApplication(item.id, item.version, {
              selectedPlanVersionId: overrideVersion.trim() || null,
              confirmUnavailable: unavailable,
              unavailableReason: unavailableReason.trim(),
              confirmVersionOverride: overrideConfirmed,
              overrideReason: overrideReason.trim(),
              openingNote: openingNote.trim(),
            });
            setItem(await getAdminPlanApplication(id));
            setActivateOpen(false);
          } catch (reason) {
            setActionError(userMessage(reason));
          } finally {
            setActivating(false);
          }
        }}
        okText="确认开通"
      >
        <Space orientation="vertical" style={{ width: "100%" }}>
          <Alert
            type="warning"
            showIcon
            title={`确认后将立即为客户开通“${String(item.public_plan_snapshot.name)}”`}
            description="客户当前使用免费套餐时，系统会自动切换到正式套餐，并立即发放对应额度。"
          />
          {actionError && <Alert type="error" showIcon title={actionError} />}
          <Form layout="vertical" style={{ width: "100%" }}>
            <Form.Item label="开通备注（选填）">
              <Input.TextArea
                aria-label="开通备注"
                value={openingNote}
                placeholder="例如：客户已确认开通专业版"
                maxLength={500}
                autoSize={{ minRows: 2, maxRows: 4 }}
                onChange={(event) => setOpeningNote(event.target.value)}
              />
            </Form.Item>
          </Form>
          <Collapse
            ghost
            items={[
              {
                key: "special",
                label: "特殊情况（通常无需填写）",
                children: (
                  <Form layout="vertical">
                    <Checkbox
                      checked={unavailable}
                      onChange={(event) => setUnavailable(event.target.checked)}
                    >
                      确认开通已下架套餐或历史版本
                    </Checkbox>
                    <Form.Item label="特殊状态开通原因" style={{ marginTop: 12 }}>
                      <Input
                        aria-label="特殊状态开通原因"
                        value={unavailableReason}
                        disabled={!unavailable}
                        placeholder="请说明仍需开通的原因"
                        maxLength={500}
                        onChange={(event) => setUnavailableReason(event.target.value)}
                      />
                    </Form.Item>
                    {canOverride && (
                      <>
                        <Form.Item label="更换后的套餐版本编号">
                          <Input
                            aria-label="更换后的套餐版本编号"
                            value={overrideVersion}
                            placeholder="仅在需要更换申请版本时填写"
                            onChange={(event) => setOverrideVersion(event.target.value)}
                          />
                        </Form.Item>
                        <Checkbox
                          checked={overrideConfirmed}
                          onChange={(event) => setOverrideConfirmed(event.target.checked)}
                        >
                          确认更换申请绑定版本
                        </Checkbox>
                        <Form.Item label="更换版本原因" style={{ marginTop: 12 }}>
                          <Input
                            aria-label="更换版本原因"
                            value={overrideReason}
                            disabled={!overrideVersion.trim()}
                            placeholder="请说明更换版本的原因"
                            maxLength={500}
                            onChange={(event) => setOverrideReason(event.target.value)}
                          />
                        </Form.Item>
                      </>
                    )}
                  </Form>
                ),
              },
            ]}
          />
        </Space>
      </Modal>
    </main>
  );
}
