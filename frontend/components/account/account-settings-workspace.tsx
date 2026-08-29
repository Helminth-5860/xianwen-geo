"use client";

import {
  BgColorsOutlined,
  LockOutlined,
  MobileOutlined,
  SafetyCertificateOutlined,
  UserOutlined,
} from "@ant-design/icons";
import {
  Alert,
  Avatar,
  Button,
  Card,
  Form,
  Input,
  Radio,
  Space,
  Spin,
  Typography,
  message,
  type FormInstance,
} from "antd";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { phoneRules } from "@/components/auth/sms-code-field";
import { useSubjectWorkspace } from "@/components/subject-workspace-context";
import {
  useAppTheme,
  type AppearanceMode,
  type AppearancePreference,
  type ColorTheme,
} from "@/components/theme";
import {
  changeAccountPassword,
  changeAccountPhone,
  requestPhoneChangeCode,
  revokeOtherSessions,
  updateAccountProfile,
  userMessage,
} from "@/lib/auth-client";
import { validateConfirmation, validatePassword } from "@/lib/auth-validation";
import { focusFirstInvalidField } from "@/lib/form-focus";

import styles from "./account-settings-workspace.module.css";

const { Paragraph, Text, Title } = Typography;

type ProfileValues = { nickname: string };
type PhoneValues = { phone: string; currentPassword: string; code: string };
type PasswordValues = {
  currentPassword: string;
  newPassword: string;
  passwordConfirmation: string;
};
type SessionValues = { currentPassword: string };

const modeOptions: ReadonlyArray<{ label: string; value: AppearanceMode }> = [
  { label: "浅色模式", value: "light" },
  { label: "深色模式", value: "dark" },
  { label: "跟随系统", value: "system" },
];

const accentOptions: ReadonlyArray<{
  value: ColorTheme;
  label: string;
  color: string;
}> = [
  { value: "blue", label: "显问蓝", color: "#2468d8" },
  { value: "green", label: "青绿色", color: "#16866f" },
  { value: "purple", label: "紫罗兰", color: "#7659c7" },
  { value: "orange", label: "暖橙色", color: "#c76a20" },
];

function nicknameInitial(nickname: string) {
  return Array.from(nickname.trim())[0] || "用";
}

function sameAppearance(left: AppearancePreference, right: AppearancePreference) {
  return left.mode === right.mode && left.accent === right.accent;
}

function SensitivePasswordField({
  form,
  fieldId,
  ariaLabel,
  name = "currentPassword",
  label = "当前密码",
}: Readonly<{
  form: FormInstance;
  fieldId: string;
  ariaLabel: string;
  name?: string;
  label?: string;
}>) {
  return (
    <Form.Item
      name={name}
      label={label}
      htmlFor={fieldId}
      rules={[{ required: true, message: `请输入${label}` }]}
    >
      <Input.Password
        id={fieldId}
        aria-label={ariaLabel}
        autoComplete="current-password"
        placeholder={`请输入${label}`}
        onPressEnter={() => form.submit()}
      />
    </Form.Item>
  );
}

export function AccountSettingsWorkspace() {
  const router = useRouter();
  const { loading, refresh, user } = useSubjectWorkspace();
  const [messageApi, messageHolder] = message.useMessage();
  const [profileForm] = Form.useForm<ProfileValues>();
  const [phoneForm] = Form.useForm<PhoneValues>();
  const [passwordForm] = Form.useForm<PasswordValues>();
  const [sessionForm] = Form.useForm<SessionValues>();
  const [savingProfile, setSavingProfile] = useState(false);
  const [sendingCode, setSendingCode] = useState(false);
  const [codeRemaining, setCodeRemaining] = useState(0);
  const [changingPhone, setChangingPhone] = useState(false);
  const [changingPassword, setChangingPassword] = useState(false);
  const [revokingSessions, setRevokingSessions] = useState(false);
  const [savingTheme, setSavingTheme] = useState(false);
  const [profileError, setProfileError] = useState("");
  const [phoneError, setPhoneError] = useState("");
  const [passwordError, setPasswordError] = useState("");
  const [sessionError, setSessionError] = useState("");
  const {
    accent,
    effectiveMode,
    mode,
    previewAppearance,
    resetPreview,
    saveAppearance,
    savedAppearance,
  } = useAppTheme();
  const resetPreviewRef = useRef(resetPreview);

  useEffect(() => {
    resetPreviewRef.current = resetPreview;
  }, [resetPreview]);

  useEffect(
    () => () => {
      resetPreviewRef.current();
    },
    [],
  );

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
    if (!loading && user && user.commercial_identity !== "USER") router.replace(user.home_route);
  }, [loading, router, user]);

  useEffect(() => {
    if (user) profileForm.setFieldsValue({ nickname: user.nickname });
  }, [profileForm, user]);

  useEffect(() => {
    if (codeRemaining <= 0) return;
    const timer = window.setTimeout(
      () => setCodeRemaining((remaining) => Math.max(0, remaining - 1)),
      1000,
    );
    return () => window.clearTimeout(timer);
  }, [codeRemaining]);

  if (loading || !user || user.commercial_identity !== "USER") {
    return (
      <main className={styles.loading} aria-label="正在加载账号设置" aria-busy="true">
        <Spin size="large" />
      </main>
    );
  }

  const saveProfile = async (values: ProfileValues) => {
    setProfileError("");
    setSavingProfile(true);
    try {
      await updateAccountProfile({ nickname: values.nickname });
      await refresh();
      messageApi.success("昵称已更新");
    } catch (error) {
      setProfileError(userMessage(error));
    } finally {
      setSavingProfile(false);
    }
  };

  const sendPhoneCode = async () => {
    if (sendingCode || codeRemaining > 0) return;
    setPhoneError("");
    try {
      const values = await phoneForm.validateFields(["phone", "currentPassword"]);
      setSendingCode(true);
      const result = await requestPhoneChangeCode({
        phone: values.phone,
        currentPassword: values.currentPassword,
      });
      setCodeRemaining(result.resend_after);
      messageApi.success("验证码已发送，请查看新手机号");
    } catch (error) {
      if (error instanceof Error) setPhoneError(userMessage(error));
    } finally {
      setSendingCode(false);
    }
  };

  const changePhone = async (values: PhoneValues) => {
    setPhoneError("");
    setChangingPhone(true);
    try {
      await changeAccountPhone({
        phone: values.phone,
        currentPassword: values.currentPassword,
        code: values.code,
      });
      router.replace("/login");
      router.refresh();
    } catch (error) {
      setPhoneError(userMessage(error));
      setChangingPhone(false);
    }
  };

  const changePassword = async (values: PasswordValues) => {
    setPasswordError("");
    setChangingPassword(true);
    try {
      await changeAccountPassword({
        currentPassword: values.currentPassword,
        newPassword: values.newPassword,
      });
      router.replace("/login");
      router.refresh();
    } catch (error) {
      setPasswordError(userMessage(error));
      setChangingPassword(false);
    }
  };

  const revokeSessions = async (values: SessionValues) => {
    setSessionError("");
    setRevokingSessions(true);
    try {
      await revokeOtherSessions(values.currentPassword);
      sessionForm.resetFields();
      messageApi.success("其他设备已退出，当前设备保持登录");
    } catch (error) {
      setSessionError(userMessage(error));
    } finally {
      setRevokingSessions(false);
    }
  };

  const saveTheme = async () => {
    setSavingTheme(true);
    try {
      await saveAppearance({ mode, accent });
      await refresh();
      messageApi.success("外观设置已保存");
    } catch (error) {
      messageApi.error(userMessage(error));
    } finally {
      setSavingTheme(false);
    }
  };

  const appearance = { mode, accent } satisfies AppearancePreference;
  const appearanceDirty = !sameAppearance(appearance, savedAppearance);
  const selectedAccent = accentOptions.find((option) => option.value === accent)?.label ?? "显问蓝";

  return (
    <main className={styles.page}>
      {messageHolder}
      <header className={styles.header}>
        <div>
          <Text className={styles.eyebrow}>个人中心</Text>
          <Title level={1}>账号设置</Title>
          <Paragraph type="secondary">管理登录信息、账号安全和你喜欢的界面外观。</Paragraph>
        </div>
        <div className={styles.accountSummary}>
          <Avatar size={52} className={styles.summaryAvatar}>
            {nicknameInitial(user.nickname)}
          </Avatar>
          <span>
            <strong>{user.nickname}</strong>
            <small>{user.phone_masked}</small>
          </span>
        </div>
      </header>

      <Card
        className={styles.card}
        title={
          <Space>
            <UserOutlined />
            个人资料
          </Space>
        }
      >
        {profileError ? <Alert type="error" showIcon message={profileError} role="alert" /> : null}
        <Form
          form={profileForm}
          layout="vertical"
          requiredMark={false}
          className={styles.compactForm}
          onFinish={saveProfile}
          onFinishFailed={focusFirstInvalidField(profileForm)}
          disabled={savingProfile}
        >
          <Form.Item
            name="nickname"
            label="昵称"
            rules={[
              { required: true, whitespace: true, message: "请输入昵称" },
              { max: 50, message: "昵称不能超过 50 个字符" },
              { pattern: /^[^\u0000-\u001f\u007f-\u009f]+$/, message: "昵称包含无法使用的字符" },
            ]}
          >
            <Input autoComplete="nickname" maxLength={50} placeholder="请输入昵称" />
          </Form.Item>
          <Form.Item label="当前登录手机号">
            <Input value={user.phone_masked} readOnly aria-label="当前登录手机号" />
          </Form.Item>
          <Button type="primary" htmlType="submit" loading={savingProfile}>
            保存个人资料
          </Button>
        </Form>
      </Card>

      <Card
        id="appearance"
        className={styles.card}
        title={
          <Space>
            <BgColorsOutlined />
            外观设置
          </Space>
        }
      >
        <div className={styles.appearanceSection}>
          <div>
            <Title level={4}>显示模式</Title>
            <Text type="secondary">选择浅色、深色，或让界面跟随设备设置。</Text>
          </div>
          <Radio.Group
            className={styles.modeChoices}
            optionType="button"
            buttonStyle="solid"
            value={mode}
            options={[...modeOptions]}
            onChange={(event) =>
              previewAppearance({ mode: event.target.value as AppearanceMode, accent })
            }
          />
        </div>
        <div className={styles.appearanceSection}>
          <div>
            <Title level={4}>主题颜色</Title>
            <Text type="secondary">主题颜色只影响你的账号，不会改变其他成员的界面。</Text>
          </div>
          <div className={styles.accentChoices} role="group" aria-label="选择主题颜色">
            {accentOptions.map((option) => (
              <button
                key={option.value}
                type="button"
                className={styles.accentChoice}
                aria-pressed={accent === option.value}
                onClick={() => previewAppearance({ mode, accent: option.value })}
              >
                <span style={{ backgroundColor: option.color }} aria-hidden="true" />
                {option.label}
              </button>
            ))}
          </div>
        </div>
        <div className={styles.appearanceFooter}>
          <Text type="secondary">
            当前预览：{effectiveMode === "dark" ? "深色模式" : "浅色模式"} · {selectedAccent}
          </Text>
          <Space wrap>
            <Button disabled={!appearanceDirty || savingTheme} onClick={resetPreview}>
              恢复已保存设置
            </Button>
            <Button
              type="primary"
              disabled={!appearanceDirty}
              loading={savingTheme}
              onClick={() => void saveTheme()}
            >
              保存外观设置
            </Button>
          </Space>
        </div>
      </Card>

      <section className={styles.securitySection} aria-labelledby="account-security-title">
        <div className={styles.sectionHeading}>
          <SafetyCertificateOutlined />
          <div>
            <Title id="account-security-title" level={2}>
              账号安全
            </Title>
            <Text type="secondary">修改重要登录信息时，需要验证当前密码。</Text>
          </div>
        </div>

        <div className={styles.securityGrid}>
          <Card
            className={styles.card}
            title={
              <Space>
                <MobileOutlined />
                更换手机号
              </Space>
            }
          >
            <Paragraph type="secondary">
              验证码会发送到新手机号。更换成功后，所有设备都需要使用新手机号重新登录。
            </Paragraph>
            {phoneError ? <Alert type="error" showIcon message={phoneError} role="alert" /> : null}
            <Form
              form={phoneForm}
              layout="vertical"
              requiredMark={false}
              onFinish={changePhone}
              onFinishFailed={focusFirstInvalidField(phoneForm)}
              disabled={changingPhone}
            >
              <Form.Item name="phone" label="新手机号" rules={phoneRules}>
                <Input inputMode="tel" autoComplete="tel" placeholder="请输入新手机号" />
              </Form.Item>
              <SensitivePasswordField
                form={phoneForm}
                fieldId="phone-current-password"
                ariaLabel="更换手机号当前密码"
              />
              <Form.Item label="短信验证码" required>
                <Space.Compact block>
                  <Form.Item
                    name="code"
                    noStyle
                    rules={[
                      { required: true, message: "请输入短信验证码" },
                      { pattern: /^\d{6}$/, message: "请输入 6 位数字验证码" },
                    ]}
                  >
                    <Input
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      aria-label="更换手机号短信验证码"
                    />
                  </Form.Item>
                  <Button
                    type="default"
                    loading={sendingCode}
                    disabled={sendingCode || codeRemaining > 0}
                    aria-label={
                      codeRemaining > 0 ? `${codeRemaining} 秒后重新发送` : "发送短信验证码"
                    }
                    onClick={() => void sendPhoneCode()}
                  >
                    {codeRemaining > 0 ? `${codeRemaining} 秒` : "发送验证码"}
                  </Button>
                </Space.Compact>
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={changingPhone}>
                确认更换手机号
              </Button>
            </Form>
          </Card>

          <Card
            className={styles.card}
            title={
              <Space>
                <LockOutlined />
                修改密码
              </Space>
            }
          >
            <Paragraph type="secondary">
              新密码至少需要 10 个字符。修改成功后，所有设备都需要重新登录。
            </Paragraph>
            {passwordError ? (
              <Alert type="error" showIcon message={passwordError} role="alert" />
            ) : null}
            <Form
              form={passwordForm}
              layout="vertical"
              requiredMark={false}
              onFinish={changePassword}
              onFinishFailed={focusFirstInvalidField(passwordForm)}
              disabled={changingPassword}
            >
              <SensitivePasswordField
                form={passwordForm}
                fieldId="password-current-password"
                ariaLabel="修改密码当前密码"
              />
              <Form.Item
                name="newPassword"
                label="新密码"
                rules={[
                  { required: true, message: "请输入新密码" },
                  { validator: (_, value: string) => validatePassword(value || "") },
                ]}
              >
                <Input.Password autoComplete="new-password" placeholder="至少 10 个字符" />
              </Form.Item>
              <Form.Item
                name="passwordConfirmation"
                label="确认新密码"
                dependencies={["newPassword"]}
                rules={[
                  { required: true, message: "请再次输入新密码" },
                  {
                    validator: (_, value: string) =>
                      validateConfirmation(
                        passwordForm.getFieldValue("newPassword") || "",
                        value || "",
                      ),
                  },
                ]}
              >
                <Input.Password autoComplete="new-password" placeholder="再次输入新密码" />
              </Form.Item>
              <Button type="primary" htmlType="submit" loading={changingPassword}>
                确认修改密码
              </Button>
            </Form>
          </Card>
        </div>

        <Card className={styles.card} title="登录设备管理">
          <div className={styles.sessionLayout}>
            <div>
              <Title level={4}>退出其他设备</Title>
              <Paragraph type="secondary">
                如果发现陌生设备，验证当前密码后可以让其他设备全部退出，当前设备保持登录。
              </Paragraph>
            </div>
            <Form
              form={sessionForm}
              layout="vertical"
              requiredMark={false}
              className={styles.sessionForm}
              onFinish={revokeSessions}
              onFinishFailed={focusFirstInvalidField(sessionForm)}
              disabled={revokingSessions}
            >
              {sessionError ? (
                <Alert type="error" showIcon message={sessionError} role="alert" />
              ) : null}
              <SensitivePasswordField
                form={sessionForm}
                fieldId="sessions-current-password"
                ariaLabel="设备管理当前密码"
              />
              <Button danger htmlType="submit" loading={revokingSessions}>
                退出其他设备
              </Button>
            </Form>
          </div>
        </Card>
      </section>
    </main>
  );
}
