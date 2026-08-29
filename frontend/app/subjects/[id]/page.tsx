"use client";

import {
  AppstoreOutlined,
  ArrowLeftOutlined,
  BankOutlined,
  BookOutlined,
  DatabaseOutlined,
  EnvironmentOutlined,
  FileTextOutlined,
  GlobalOutlined,
  LinkOutlined,
  MessageOutlined,
  PhoneOutlined,
  PictureOutlined,
  PlusOutlined,
  RobotOutlined,
  SaveOutlined,
  ShopOutlined,
  ShoppingCartOutlined,
  TeamOutlined,
  UserOutlined,
  VideoCameraOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Button,
  Card,
  Collapse,
  Form,
  Input,
  InputNumber,
  Select,
  Spin,
  Tag,
  Typography,
} from "antd";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState, type ReactNode } from "react";

import { SubjectAiEnrichment } from "@/components/subject-ai-enrichment";
import { SubjectDocuments } from "@/components/subject-documents";
import { SubjectServiceAreaSelector } from "@/components/subject-service-area-selector";
import { useSubjectSwitchGuard } from "@/components/subject-workspace-context";
import { SubjectWebSources } from "@/components/subject-web-sources";
import { AuthApiError, userMessage } from "@/lib/auth-client";
import type { SubjectDocument } from "@/lib/documents-client";
import {
  emptySubjectBusinessProfile,
  getSubject,
  notifySubjectContextUpdated,
  saveSubject,
  type PersistedSubjectField,
  type SubjectBusinessProfile,
  type SubjectDetail,
  type SubjectSocialChannels,
} from "@/lib/subjects-client";

import styles from "./subject-profile.module.css";

const fieldLabels: Record<string, string> = {
  name: "营业执照主体名称",
  legal_entity_type: "主体类型",
  contact_name: "联系人",
  contact_phone: "联系电话",
  business_address: "经营地址",
  primary_business: "主营业务",
  target_audience: "目标用户",
  core_products_services: "产品 / 服务",
  service_regions: "服务区域",
  brand_name: "品牌名称",
  summary: "企业简介",
  official_url: "官网",
  douyin: "抖音",
  wechat_channels: "视频号",
  wechat_official_account: "公众号",
  xiaohongshu: "小红书",
  kuaishou: "快手",
  ecommerce_urls: "淘宝 / 天猫 / 京东 / 1688 / 拼多多等",
  other_public_urls: "其他公开网页",
};

const fieldPlaceholders: Record<string, string> = {
  name: "请输入营业执照上的完整主体名称",
  contact_name: "请输入日常业务联系人",
  contact_phone: "请输入可联系的手机或座机",
  business_address: "请输入实际经营地址",
  primary_business: "请简要说明主要经营内容",
  target_audience: "请描述主要服务的客户群体",
  brand_name: "如对外品牌与营业执照名称不同，请填写品牌名称",
  summary: "用简洁、客观的语言介绍企业业务与优势",
  official_url: "https://example.com",
  douyin: "填写账号名称或公开主页链接",
  wechat_channels: "填写视频号名称或公开资料",
  wechat_official_account: "填写公众号名称",
  xiaohongshu: "填写账号名称或公开主页链接",
  kuaishou: "填写账号名称或公开主页链接",
  ecommerce_urls: "每行填写一个店铺或商品公开链接",
  other_public_urls: "每行填写一个可公开访问的网页",
};

const baseIdentityKeys = new Set([
  "name",
  "legal_entity_type",
  "contact_name",
  "contact_phone",
  "business_address",
]);
const businessKeys = new Set([
  "primary_business",
  "target_audience",
  "core_products_services",
  "service_regions",
]);
const requiredProfileKeys = new Set([...baseIdentityKeys, ...businessKeys]);

type DirectProfileFieldKey = Exclude<keyof SubjectBusinessProfile, "social_channels">;
type ProfileFieldKey = DirectProfileFieldKey | keyof SubjectSocialChannels;

type ProfileField = Readonly<{
  key: ProfileFieldKey;
  label: string;
  required: boolean;
  wide?: boolean;
  textarea?: boolean;
}>;

const profileFields: Record<ProfileFieldKey, ProfileField> = {
  legal_entity_type: {
    key: "legal_entity_type",
    label: fieldLabels.legal_entity_type,
    required: true,
  },
  contact_name: { key: "contact_name", label: fieldLabels.contact_name, required: true },
  contact_phone: { key: "contact_phone", label: fieldLabels.contact_phone, required: true },
  business_address: {
    key: "business_address",
    label: fieldLabels.business_address,
    required: true,
    wide: true,
  },
  primary_business: {
    key: "primary_business",
    label: fieldLabels.primary_business,
    required: true,
    wide: true,
    textarea: true,
  },
  brand_name: { key: "brand_name", label: fieldLabels.brand_name, required: false },
  douyin: { key: "douyin", label: fieldLabels.douyin, required: false },
  wechat_channels: {
    key: "wechat_channels",
    label: fieldLabels.wechat_channels,
    required: false,
  },
  wechat_official_account: {
    key: "wechat_official_account",
    label: fieldLabels.wechat_official_account,
    required: false,
  },
  xiaohongshu: { key: "xiaohongshu", label: fieldLabels.xiaohongshu, required: false },
  kuaishou: { key: "kuaishou", label: fieldLabels.kuaishou, required: false },
  ecommerce_urls: {
    key: "ecommerce_urls",
    label: fieldLabels.ecommerce_urls,
    required: false,
    wide: true,
    textarea: true,
  },
  other_public_urls: {
    key: "other_public_urls",
    label: fieldLabels.other_public_urls,
    required: false,
    wide: true,
    textarea: true,
  },
};

const requiredBusinessProfileFields = [
  profileFields.legal_entity_type,
  profileFields.contact_name,
  profileFields.contact_phone,
  profileFields.business_address,
  profileFields.primary_business,
];

const socialProfileFieldKeys = new Set<ProfileFieldKey>([
  "douyin",
  "wechat_channels",
  "wechat_official_account",
  "xiaohongshu",
  "kuaishou",
  "ecommerce_urls",
  "other_public_urls",
]);

function fieldIcon(key: string): ReactNode {
  switch (key) {
    case "name":
      return <BankOutlined />;
    case "legal_entity_type":
      return <ShopOutlined />;
    case "contact_name":
      return <UserOutlined />;
    case "contact_phone":
      return <PhoneOutlined />;
    case "business_address":
    case "service_regions":
      return <EnvironmentOutlined />;
    case "primary_business":
      return <ShopOutlined />;
    case "target_audience":
      return <TeamOutlined />;
    case "core_products_services":
      return <AppstoreOutlined />;
    case "brand_name":
      return <BankOutlined />;
    case "summary":
      return <FileTextOutlined />;
    case "official_url":
      return <GlobalOutlined />;
    case "wechat_official_account":
      return <MessageOutlined />;
    case "douyin":
    case "wechat_channels":
    case "kuaishou":
      return <VideoCameraOutlined />;
    case "xiaohongshu":
      return <BookOutlined />;
    case "ecommerce_urls":
      return <ShoppingCartOutlined />;
    case "other_public_urls":
      return <LinkOutlined />;
    case "logo":
      return <PictureOutlined />;
    default:
      return <FileTextOutlined />;
  }
}

function fieldLabel(key: string, label: string) {
  return (
    <span className={styles.fieldLabel}>
      <span className={styles.fieldLabelIcon}>{fieldIcon(key)}</span>
      <span>{label}</span>
    </span>
  );
}

function OptionalPanelLabel({
  icon,
  title,
  description,
  badge,
}: {
  icon: ReactNode;
  title: string;
  description: string;
  badge?: string;
}) {
  return (
    <div className={styles.optionalLabel}>
      <div className={styles.optionalLabelMain}>
        <span className={styles.optionalLabelIcon}>{icon}</span>
        <span className={styles.optionalLabelCopy}>
          <span className={styles.optionalLabelTitle}>{title}</span>
          <span className={styles.optionalLabelDescription}>{description}</span>
        </span>
      </div>
      {badge && <Tag className={styles.badge}>{badge}</Tag>}
    </div>
  );
}

function presentedField(field: PersistedSubjectField): PersistedSubjectField {
  return {
    ...field,
    label: fieldLabels[field.field_key] ?? field.label,
    required: field.required || requiredProfileKeys.has(field.field_key),
  };
}

function valueMissing(value: unknown) {
  if (value === null || value === undefined) return true;
  if (typeof value === "string") return value.trim().length === 0;
  if (Array.isArray(value)) return value.length === 0;
  return false;
}

function profileValueMissing(field: PersistedSubjectField, value: unknown) {
  if (field.field_key !== "service_regions") return valueMissing(value);
  if (typeof value !== "string" || !value.trim()) return true;
  try {
    const parsed = JSON.parse(value) as { nationwide?: unknown; areas?: unknown };
    return (
      parsed.nationwide !== true && (!Array.isArray(parsed.areas) || parsed.areas.length === 0)
    );
  } catch {
    return false;
  }
}

function normalizedValue(field: PersistedSubjectField, value: unknown): unknown {
  if (field.field_type === "multi") return Array.isArray(value) ? value : [];
  if (field.field_type === "number") return typeof value === "number" ? value : null;
  return value ?? "";
}

function valuesForSave(subject: SubjectDetail, values: Record<string, unknown>) {
  return Object.fromEntries(
    subject.form_schema.fields.map((field) => {
      const value = values[field.field_key];
      if (field.field_type === "url" && typeof value === "string" && !value.trim()) {
        return [field.field_key, null];
      }
      return [field.field_key, value];
    }),
  );
}

function subjectErrorMessage(reason: unknown, subject: SubjectDetail) {
  if (reason instanceof AuthApiError && reason.code === "SUBJECT_FIELD_VALUES_INVALID") {
    const fields = reason.details.fields;
    if (fields && typeof fields === "object" && !Array.isArray(fields)) {
      const fieldKey = Object.keys(fields)[0];
      if (fieldKey === "official_url") {
        return "官网格式不正确，请填写以 http:// 或 https:// 开头的完整网址";
      }
      const schemaField = subject.form_schema.fields.find((field) => field.field_key === fieldKey);
      return `${fieldLabels[fieldKey] ?? schemaField?.label ?? "主体资料"}格式不正确，请检查后再保存`;
    }
  }
  if (reason instanceof AuthApiError && reason.code === "VALIDATION_ERROR") {
    const firstIssue = findFirstValidationIssue(reason.details.fields);
    if (firstIssue) {
      const fieldKey = [...firstIssue.path].reverse().find((item) => item !== "profile_values");
      if (fieldKey === "official_url") {
        return "官网格式不正确，请填写以 http:// 或 https:// 开头的完整网址";
      }
      if (fieldKey === "contact_phone") {
        return "联系电话格式不正确，请填写 5 至 32 位的手机号或座机号码";
      }
      const schemaField = subject.form_schema.fields.find((field) => field.field_key === fieldKey);
      const label = fieldKey ? (fieldLabels[fieldKey] ?? schemaField?.label) : undefined;
      if (label) return `${label}格式不正确，请检查后再保存`;
    }
  }
  return userMessage(reason);
}

function findFirstValidationIssue(
  value: unknown,
  path: string[] = [],
): { path: string[]; message: string } | null {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findFirstValidationIssue(item, path);
      if (found) return found;
    }
    return null;
  }
  if (typeof value !== "object" || value === null) return null;
  const record = value as Record<string, unknown>;
  if (typeof record.message === "string") return { path, message: record.message };
  for (const [key, item] of Object.entries(record)) {
    const found = findFirstValidationIssue(item, [...path, key]);
    if (found) return found;
  }
  return null;
}

function businessProfileValue(profile: SubjectBusinessProfile, key: ProfileFieldKey): string {
  if (socialProfileFieldKeys.has(key)) {
    return profile.social_channels[key as keyof SubjectSocialChannels];
  }
  return profile[key as DirectProfileFieldKey];
}

function ProfileFieldInput({
  field,
  value,
  disabled,
  onChange,
}: {
  field: ProfileField;
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
}) {
  if (field.key === "legal_entity_type") {
    return (
      <Select
        aria-label={field.label}
        value={value || undefined}
        disabled={disabled}
        prefix={fieldIcon(field.key)}
        placeholder="请选择公司或个体工商户"
        style={{ width: "100%" }}
        options={[
          { value: "company", label: "公司" },
          { value: "individual_business", label: "个体工商户" },
        ]}
        onChange={onChange}
      />
    );
  }
  if (field.textarea) {
    return (
      <Input.TextArea
        aria-label={field.label}
        value={value}
        disabled={disabled}
        placeholder={fieldPlaceholders[field.key]}
        rows={field.key === "primary_business" ? 4 : 3}
        onChange={(event) => onChange(event.target.value)}
      />
    );
  }
  return (
    <Input
      aria-label={field.label}
      value={value}
      disabled={disabled}
      prefix={fieldIcon(field.key)}
      inputMode={field.key === "contact_phone" ? "tel" : undefined}
      placeholder={fieldPlaceholders[field.key]}
      onChange={(event) => onChange(event.target.value)}
    />
  );
}

function FieldInput({
  field,
  value,
  disabled,
  documents,
  onChange,
}: {
  field: PersistedSubjectField;
  value: unknown;
  disabled: boolean;
  documents: SubjectDocument[];
  onChange: (value: unknown) => void;
}) {
  if (field.field_key === "service_regions") {
    return <SubjectServiceAreaSelector value={value} disabled={disabled} onChange={onChange} />;
  }
  if (field.field_key === "core_products_services") {
    const items =
      typeof value === "string"
        ? value
            .split(/\r?\n/)
            .map((item) => item.trim())
            .filter(Boolean)
        : [];
    return (
      <Select
        aria-label={field.label}
        mode="tags"
        value={items}
        disabled={disabled}
        prefix={fieldIcon(field.field_key)}
        tokenSeparators={[",", "，"]}
        placeholder="输入一项产品或服务后按回车，可添加多条"
        style={{ width: "100%" }}
        onChange={(next) => onChange(next.length ? next.join("\n") : null)}
      />
    );
  }
  if (field.field_type === "image" || field.field_type === "file") {
    const choices = documents.filter(
      (document) =>
        field.field_type === "file" ||
        ["jpeg", "png", "webp"].includes(document.detected_file_kind),
    );
    return (
      <Select
        aria-label={field.label}
        value={(value as { document_version_id?: string } | null)?.document_version_id}
        disabled={disabled}
        prefix={fieldIcon(field.field_key)}
        allowClear={!field.required}
        placeholder="选择资料库中已完成安全验证的文件"
        style={{ width: "100%" }}
        options={choices.map((document) => ({
          value: document.document_version_id,
          label: document.display_name,
        }))}
        onChange={(documentVersionId) =>
          onChange(documentVersionId ? { document_version_id: documentVersionId } : null)
        }
      />
    );
  }
  if (field.field_type === "textarea") {
    return (
      <Input.TextArea
        aria-label={field.label}
        value={String(normalizedValue(field, value))}
        disabled={disabled}
        placeholder={fieldPlaceholders[field.field_key]}
        rows={4}
        onChange={(event) => onChange(event.target.value || null)}
      />
    );
  }
  if (field.field_type === "number") {
    return (
      <InputNumber
        aria-label={field.label}
        value={normalizedValue(field, value) as number | null}
        disabled={disabled}
        prefix={fieldIcon(field.field_key)}
        style={{ width: "100%" }}
        onChange={(next) => onChange(next)}
      />
    );
  }
  if (field.field_type === "single" || field.field_type === "select") {
    return (
      <Select
        aria-label={field.label}
        value={(value as string | null) ?? undefined}
        disabled={disabled}
        prefix={fieldIcon(field.field_key)}
        allowClear={!field.required}
        style={{ width: "100%" }}
        options={field.options.map((option) => ({
          value: option.option_key,
          label: option.label,
        }))}
        onChange={(next) => onChange(next ?? null)}
      />
    );
  }
  if (field.field_type === "multi") {
    return (
      <Select
        aria-label={field.label}
        mode="multiple"
        value={normalizedValue(field, value) as string[]}
        disabled={disabled}
        prefix={fieldIcon(field.field_key)}
        style={{ width: "100%" }}
        options={field.options.map((option) => ({
          value: option.option_key,
          label: option.label,
        }))}
        onChange={onChange}
      />
    );
  }
  return (
    <Input
      aria-label={field.label}
      type={field.field_type === "date" ? "date" : "text"}
      inputMode={field.field_type === "url" ? "url" : undefined}
      value={String(normalizedValue(field, value))}
      disabled={disabled}
      prefix={fieldIcon(field.field_key)}
      placeholder={fieldPlaceholders[field.field_key]}
      onChange={(event) => onChange(event.target.value || null)}
    />
  );
}

function SubjectDetailContent() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const readOnly = searchParams.get("mode") === "view";
  const [subject, setSubject] = useState<SubjectDetail>();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [businessProfile, setBusinessProfile] = useState<SubjectBusinessProfile>(
    emptySubjectBusinessProfile,
  );
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [saving, setSaving] = useState(false);
  const [documents, setDocuments] = useState<SubjectDocument[]>([]);

  const updateBusinessProfileField = (key: ProfileFieldKey, value: string) => {
    setError("");
    setNotice("");
    setBusinessProfile((current) => {
      if (socialProfileFieldKeys.has(key)) {
        return {
          ...current,
          social_channels: {
            ...current.social_channels,
            [key]: value,
          },
        };
      }
      return { ...current, [key]: value } as SubjectBusinessProfile;
    });
  };

  useEffect(() => {
    let current = true;
    void getSubject(params.id)
      .then((data) => {
        if (!current) return;
        setSubject(data);
        setValues(data.draft_values);
        setBusinessProfile(data.business_profile);
      })
      .catch((reason) => {
        if (current) setError(userMessage(reason));
      });
    return () => {
      current = false;
    };
  }, [params.id]);

  const validationMessage = (
    currentSubject: SubjectDetail,
    currentValues: Record<string, unknown>,
    currentProfile: SubjectBusinessProfile,
  ) => {
    const missing = currentSubject.form_schema.fields
      .map(presentedField)
      .filter(
        (field) => field.required && profileValueMissing(field, currentValues[field.field_key]),
      );
    if (missing.length) {
      return `请先填写：${missing.map((field) => field.label).join("、")}`;
    }
    const missingProfile = requiredBusinessProfileFields.filter((field) =>
      valueMissing(businessProfileValue(currentProfile, field.key)),
    );
    if (missingProfile.length) {
      return `请先填写：${missingProfile.map((field) => field.label).join("、")}`;
    }
    return "";
  };

  const persist = async (
    currentSubject: SubjectDetail,
    currentValues: Record<string, unknown>,
    currentProfile: SubjectBusinessProfile,
    showSuccess: boolean,
  ) => {
    const invalid = validationMessage(currentSubject, currentValues, currentProfile);
    if (invalid) throw new Error(invalid);
    const isCreating = currentSubject.current_version_no === null;
    const result = await saveSubject(
      currentSubject,
      valuesForSave(currentSubject, currentValues),
      currentProfile,
    );
    setSubject(result.subject);
    setValues(result.subject.draft_values);
    setBusinessProfile(result.subject.business_profile);
    notifySubjectContextUpdated();
    setError("");
    if (showSuccess) {
      setNotice(isCreating ? "主体已新增，资料已生效" : "修改已保存，资料已生效");
    }
    return result.subject;
  };

  const save = async () => {
    if (!subject) return true;
    setSaving(true);
    try {
      await persist(subject, values, businessProfile, true);
      return true;
    } catch (reason) {
      setNotice("");
      setError(subjectErrorMessage(reason, subject));
      return false;
    } finally {
      setSaving(false);
    }
  };

  const dirty = useMemo(
    () =>
      Boolean(
        subject &&
        !readOnly &&
        (JSON.stringify(values) !== JSON.stringify(subject.draft_values) ||
          JSON.stringify(businessProfile) !== JSON.stringify(subject.business_profile)),
      ),
    [businessProfile, readOnly, subject, values],
  );
  useSubjectSwitchGuard(`subject-profile:${params.id}`, dirty, save);

  if (!subject && !error) {
    return <Spin fullscreen description="正在加载企业资料" />;
  }

  const renderBusinessProfileField = (field: ProfileField) => (
    <Form.Item
      key={field.key}
      className={`${styles.fieldItem} ${field.wide ? styles.fieldWide : ""}`}
      label={fieldLabel(field.key, field.label)}
      required={field.required}
    >
      <ProfileFieldInput
        field={field}
        value={businessProfileValue(businessProfile, field.key)}
        disabled={readOnly || subject?.status === "archived"}
        onChange={(value) => updateBusinessProfileField(field.key, value)}
      />
    </Form.Item>
  );

  const renderSchemaField = (rawField: PersistedSubjectField) => {
    const field = presentedField(rawField);
    const wide = [
      "business_address",
      "primary_business",
      "target_audience",
      "core_products_services",
      "service_regions",
      "summary",
      "ecommerce_urls",
      "other_public_urls",
    ].includes(field.field_key);
    return (
      <Form.Item
        key={field.field_key}
        className={`${styles.fieldItem} ${wide ? styles.fieldWide : ""}`}
        label={fieldLabel(field.field_key, field.label)}
        required={field.required}
        extra={field.description}
      >
        <FieldInput
          field={field}
          value={values[field.field_key]}
          disabled={readOnly || subject?.status === "archived"}
          documents={documents}
          onChange={(value) => {
            setError("");
            setNotice("");
            setValues((current) => ({
              ...current,
              [field.field_key]: value,
            }));
          }}
        />
      </Form.Item>
    );
  };

  return (
    <main className={`page-shell ${styles.page}`}>
      <Link href="/subjects" className={styles.backLink}>
        <ArrowLeftOutlined />
        返回主体管理
      </Link>
      {error && <Alert className={styles.alert} type="error" showIcon message={error} />}
      {notice && (
        <Alert
          className={styles.alert}
          type="success"
          showIcon
          message={notice}
          description="你可以继续完善选填资料，或返回主体管理查看当前主体。"
        />
      )}
      {subject && (
        <>
          <header className={styles.hero}>
            <div className={styles.heroIcon} aria-hidden="true">
              <BankOutlined />
            </div>
            <div className={styles.heroContent}>
              <Typography.Text className={styles.eyebrow}>主体档案</Typography.Text>
              <Typography.Title className={styles.heroTitle}>
                {readOnly
                  ? "查看主体档案"
                  : subject.current_version_no === null
                    ? "新增主体"
                    : "编辑主体"}
              </Typography.Title>
              <Typography.Paragraph className={styles.heroDescription}>
                {readOnly
                  ? "查看已保存的企业经营、品牌与公开资料。"
                  : "填写真实经营资料，建立清晰的企业档案，为后续 GEO 分析、内容生成和品牌建设提供可靠基础。"}
              </Typography.Paragraph>
            </div>
            <div className={styles.statuses}>
              {subject.status === "archived" ? (
                <Tag>已删除</Tag>
              ) : subject.current_version_no === null ? (
                <Tag color="orange">待完善</Tag>
              ) : (
                <Tag color="green">可用</Tag>
              )}
              {subject.is_current && <Tag color="blue">当前</Tag>}
              {readOnly && subject.status !== "archived" && (
                <Button href={`/subjects/${subject.id}`}>编辑主体</Button>
              )}
            </div>
          </header>

          {subject.risk.public_reason && (
            <Alert
              className={styles.alert}
              type="warning"
              showIcon
              message="资料提示"
              description={subject.risk.public_reason}
            />
          )}

          <Form layout="vertical" className={styles.formStack}>
            {[
              {
                key: "identity",
                title: "基础身份信息",
                description: "用于确认企业经营主体和日常联系方式",
                icon: <BankOutlined />,
                fields: subject.form_schema.fields.filter((field) =>
                  baseIdentityKeys.has(field.field_key),
                ),
                profileBefore: [] as ProfileField[],
                profileAfter: [
                  profileFields.legal_entity_type,
                  profileFields.contact_name,
                  profileFields.contact_phone,
                  profileFields.business_address,
                ],
              },
              {
                key: "business",
                title: "经营信息",
                description: "帮助系统理解你提供什么、服务谁，以及覆盖哪些区域",
                icon: <ShopOutlined />,
                fields: subject.form_schema.fields.filter((field) =>
                  businessKeys.has(field.field_key),
                ),
                profileBefore: [profileFields.primary_business],
                profileAfter: [] as ProfileField[],
              },
            ].map((section) => (
              <Card key={section.key} className={styles.sectionCard}>
                <section>
                  <div className={styles.sectionHeader}>
                    <div className={styles.sectionHeading}>
                      <span className={styles.sectionIcon}>{section.icon}</span>
                      <div className={styles.sectionCopy}>
                        <Typography.Title className={styles.sectionTitle} level={4}>
                          {section.title}
                        </Typography.Title>
                        <Typography.Text className={styles.sectionDescription}>
                          {section.description}
                        </Typography.Text>
                      </div>
                    </div>
                    <Tag className={`${styles.badge} ${styles.badgeRequired}`}>必填</Tag>
                  </div>
                  <div className={styles.fieldGrid}>
                    {section.profileBefore.map(renderBusinessProfileField)}
                    {section.fields.map(renderSchemaField)}
                    {section.profileAfter.map(renderBusinessProfileField)}
                  </div>
                </section>
              </Card>
            ))}

            <Collapse
              className={styles.optionalCollapse}
              expandIconPosition="end"
              items={[
                {
                  key: "public",
                  label: (
                    <OptionalPanelLabel
                      icon={<GlobalOutlined />}
                      title="品牌与公开资料"
                      description="品牌名称、官网、公众号、抖音、小红书以及公开电商渠道"
                      badge="选填"
                    />
                  ),
                  children: (
                    <div className={styles.fieldGrid}>
                      {renderBusinessProfileField(profileFields.brand_name)}
                      {subject.form_schema.fields
                        .filter(
                          (field) =>
                            !baseIdentityKeys.has(field.field_key) &&
                            !businessKeys.has(field.field_key),
                        )
                        .map(renderSchemaField)}
                      <div className={styles.publicSubheading}>
                        <GlobalOutlined className={styles.publicSubheadingIcon} />
                        公开渠道
                      </div>
                      {[
                        profileFields.douyin,
                        profileFields.wechat_channels,
                        profileFields.wechat_official_account,
                        profileFields.xiaohongshu,
                        profileFields.kuaishou,
                        profileFields.ecommerce_urls,
                        profileFields.other_public_urls,
                      ].map(renderBusinessProfileField)}
                    </div>
                  ),
                },
              ]}
            />
          </Form>

          <Collapse
            className={styles.optionalCollapse}
            expandIconPosition="end"
            items={[
              {
                key: "sources",
                label: (
                  <OptionalPanelLabel
                    icon={<DatabaseOutlined />}
                    title="更多资料来源"
                    description="补充宣传册、产品资料、企业公开网页等可信信息"
                    badge="选填"
                  />
                ),
                children: (
                  <>
                    <Typography.Paragraph className={styles.sourcesIntro}>
                      可上传宣传册、PDF、产品资料，或导入企业公开网页；这些资料只用于补充主体档案。
                    </Typography.Paragraph>
                    <SubjectDocuments
                      subjectId={subject.id}
                      disabled={readOnly || subject.status === "archived"}
                      onDocumentsChange={setDocuments}
                    />
                    <SubjectWebSources
                      subjectId={subject.id}
                      disabled={readOnly || subject.status === "archived"}
                    />
                  </>
                ),
              },
            ]}
          />

          {!readOnly && subject.status !== "archived" && (
            <Collapse
              className={`${styles.optionalCollapse} ${styles.optionalCollapseAi}`}
              expandIconPosition="end"
              items={[
                {
                  key: "ai",
                  label: (
                    <OptionalPanelLabel
                      icon={<RobotOutlined />}
                      title="AI 帮我补充资料"
                      description="根据已有资料辅助整理企业信息，不会自动覆盖已确认内容"
                    />
                  ),
                  children: (
                    <>
                      <div className={styles.aiIntro}>
                        <RobotOutlined />
                        <span>
                          AI 建议会先展示给你确认，再写入主体档案；已经填写并确认的资料不会被自动覆盖。
                        </span>
                      </div>
                      <SubjectAiEnrichment
                        subject={subject}
                        disabled={false}
                        onSyncBeforeStart={() => persist(subject, values, businessProfile, false)}
                        onApplied={(updated) =>
                          persist(updated, updated.draft_values, businessProfile, false)
                        }
                      />
                    </>
                  ),
                },
              ]}
            />
          )}

          {!readOnly && subject.status !== "archived" && (
            <div className={styles.actionBar}>
              <div className={styles.actionCopy}>
                <span className={styles.actionTitle}>
                  {subject.current_version_no === null ? "创建企业主体档案" : "保存主体资料修改"}
                </span>
                <span className={styles.actionDescription}>
                  保存后资料立即生效，但不会自动进入关键词配置或启动 GEO 工作。
                </span>
              </div>
              <div className={styles.actionButtons}>
                <Button className={styles.secondaryButton} href="/subjects">
                  取消
                </Button>
                <Button
                  className={styles.primaryButton}
                  type="primary"
                  loading={saving}
                  icon={subject.current_version_no === null ? <PlusOutlined /> : <SaveOutlined />}
                  onClick={() => void save()}
                >
                  {subject.current_version_no === null ? "新增主体" : "保存修改"}
                </Button>
              </div>
            </div>
          )}

          <Typography.Paragraph className={styles.versionLink}>
            <Link href={`/subjects/${subject.id}/versions`}>查看资料更新记录</Link>
          </Typography.Paragraph>
        </>
      )}
    </main>
  );
}

export default function SubjectDetailPage() {
  return (
    <Suspense fallback={<Spin fullscreen description="正在加载企业资料" />}>
      <SubjectDetailContent />
    </Suspense>
  );
}
