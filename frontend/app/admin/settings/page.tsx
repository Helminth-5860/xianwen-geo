"use client";

import { QrcodeOutlined, UploadOutlined } from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Form,
  Image,
  Input,
  Space,
  Spin,
  Switch,
  Typography,
  Upload,
  message,
} from "antd";
import { useEffect, useState } from "react";

import { AdminPageHeader } from "@/components/admin/admin-page-header";
import { useAdminCapabilities } from "@/components/admin/admin-capability";
import { userMessage } from "@/lib/auth-client";
import {
  getAdminSalesContact,
  setAdminSalesContactEnabled,
  uploadAdminSalesContact,
  type SalesContactConfiguration,
} from "@/lib/sales-contact-client";

const ALLOWED_IMAGE_TYPES = new Set(["image/png", "image/jpeg", "image/webp"]);
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;

function formatDate(value: string | null) {
  if (!value) return "尚未更新";
  return new Date(value).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function SalesContactCard() {
  const [messageApi, messageHolder] = message.useMessage();
  const [configuration, setConfiguration] = useState<SalesContactConfiguration | null>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    void getAdminSalesContact()
      .then(setConfiguration)
      .catch((reason) => setError(userMessage(reason)))
      .finally(() => setLoading(false));
  }, []);

  const selectFile = (file: File) => {
    setError("");
    if (!ALLOWED_IMAGE_TYPES.has(file.type)) {
      setError("请选择 PNG、JPG 或 WebP 格式的二维码图片。");
      return Upload.LIST_IGNORE;
    }
    if (file.size <= 0 || file.size > MAX_IMAGE_BYTES) {
      setError("二维码图片大小需要在 5MB 以内。");
      return Upload.LIST_IGNORE;
    }
    setSelectedFile(file);
    return false;
  };

  const uploadQrCode = async () => {
    if (!selectedFile) return;
    setSaving(true);
    setError("");
    try {
      const next = await uploadAdminSalesContact(selectedFile, true);
      setConfiguration(next);
      setSelectedFile(null);
      messageApi.success(configuration?.configured ? "销售二维码已替换" : "销售二维码已保存");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  const changeEnabled = async (enabled: boolean) => {
    if (!configuration?.configured) return;
    setSaving(true);
    setError("");
    try {
      setConfiguration(await setAdminSalesContactEnabled(enabled));
      messageApi.success(enabled ? "销售联系方式已启用" : "销售联系方式已停用");
    } catch (reason) {
      setError(userMessage(reason));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      id="sales-contact"
      className="admin-surface"
      title={
        <Space>
          <QrcodeOutlined />
          销售联系方式
        </Space>
      }
    >
      {messageHolder}
      {loading ? (
        <Spin description="正在读取销售联系方式" />
      ) : (
        <Space orientation="vertical" size={18} style={{ width: "100%" }}>
          <Typography.Paragraph type="secondary" style={{ margin: 0 }}>
            {configuration?.scope === "global"
              ? "平台直营客户和未单独配置的代理客户，将看到这里的微信二维码。"
              : "由你负责的客户将优先看到这里的微信二维码；未配置时会使用平台联系方式。"}
          </Typography.Paragraph>
          {error ? <Alert type="error" showIcon title={error} role="alert" /> : null}
          <Space size={24} align="start" wrap>
            {configuration?.qr_code_url ? (
              <Image
                width={190}
                height={190}
                src={configuration.qr_code_url}
                alt="当前销售微信二维码"
                style={{ objectFit: "contain", borderRadius: 12 }}
                fallback="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='190' height='190'%3E%3Crect width='190' height='190' fill='%23f5f7fb'/%3E%3Ctext x='95' y='98' text-anchor='middle' fill='%236b7280' font-size='14'%3E图片暂时无法显示%3C/text%3E%3C/svg%3E"
              />
            ) : (
              <div
                style={{
                  width: 190,
                  height: 190,
                  display: "grid",
                  placeItems: "center",
                  border: "1px dashed var(--xw-border)",
                  borderRadius: 12,
                  color: "var(--xw-text-secondary)",
                }}
              >
                尚未上传二维码
              </div>
            )}
            <Space orientation="vertical" size={14} style={{ minWidth: 300 }}>
              <div>
                <Typography.Text strong>微信二维码</Typography.Text>
                <Typography.Paragraph type="secondary" style={{ margin: "4px 0 0" }}>
                  建议上传清晰、可长期使用的个人或企业微信二维码。
                </Typography.Paragraph>
              </div>
              <Upload
                accept="image/png,image/jpeg,image/webp"
                maxCount={1}
                showUploadList={false}
                beforeUpload={selectFile}
                disabled={saving}
              >
                <Button icon={<UploadOutlined />}>选择二维码图片</Button>
              </Upload>
              {selectedFile ? <Typography.Text>已选择：{selectedFile.name}</Typography.Text> : null}
              <Button
                type="primary"
                icon={<UploadOutlined />}
                disabled={!selectedFile}
                loading={saving}
                onClick={() => void uploadQrCode()}
              >
                {configuration?.configured ? "替换二维码" : "保存二维码"}
              </Button>
              <Space>
                <Switch
                  aria-label="启用销售联系方式"
                  checked={Boolean(configuration?.enabled)}
                  disabled={!configuration?.configured || saving}
                  onChange={(enabled) => void changeEnabled(enabled)}
                />
                <Typography.Text>
                  {configuration?.enabled ? "当前已启用" : "当前已停用"}
                </Typography.Text>
              </Space>
              <Typography.Text type="secondary">
                最近更新：{formatDate(configuration?.updated_at ?? null)}
              </Typography.Text>
            </Space>
          </Space>
        </Space>
      )}
    </Card>
  );
}

export default function AdminSettingsPage() {
  const context = useAdminCapabilities();
  const isSuperuser = context?.commercial_identity === "SUPER_ADMIN";

  return (
    <div className="admin-page">
      <AdminPageHeader
        title={isSuperuser ? "系统设置" : "销售联系方式"}
        description={
          isSuperuser
            ? "维护平台基础信息与面向客户的销售联系方式。"
            : "维护你自己的销售微信二维码，方便所负责的客户联系。"
        }
      />
      <SalesContactCard />
      {isSuperuser ? (
        <>
          <Alert
            type="info"
            showIcon
            title="其他平台信息继续沿用当前配置"
            description="品牌与注册信息暂不在此页面调整。"
            style={{ margin: "18px 0" }}
          />
          <Card className="admin-surface" title="品牌信息">
            <Form
              layout="vertical"
              disabled
              initialValues={{ platformName: "显问 GEO 智能体系统" }}
            >
              <Form.Item label="平台名称" name="platformName">
                <Input />
              </Form.Item>
              <Form.Item label="登录页介绍" name="loginDescription">
                <Input.TextArea rows={3} placeholder="介绍显问 GEO 的核心价值" />
              </Form.Item>
            </Form>
          </Card>
        </>
      ) : null}
    </div>
  );
}
