"use client";

import { LockOutlined, MessageOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, ConfigProvider, Form, Input } from "antd";
import zhCN from "antd/locale/zh_CN";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { phoneRules, SmsCodeField } from "@/components/auth/sms-code-field";
import { useSmsCode } from "@/hooks/use-sms-code";
import {
  AuthApiError,
  getCurrentUser,
  loginWithPassword,
  loginWithSms,
  userMessage,
} from "@/lib/auth-client";
import { focusFirstInvalidField } from "@/lib/form-focus";

import styles from "./login.module.css";

type LoginMode = "password" | "sms";
type LoginValues = { phone: string; password?: string; smsCode?: string };

function BrandLogo() {
  return (
    <Link href="/login" className={styles.brand} aria-label="显问 AI">
      <svg className={styles.brandIcon} viewBox="0 0 58 42" aria-hidden>
        <defs>
          <linearGradient id="xianwen-brand-gradient" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor="#09bfd2" />
            <stop offset="52%" stopColor="#3169e8" />
            <stop offset="100%" stopColor="#8126ee" />
          </linearGradient>
        </defs>
        <path
          d="M4.5 21C10.8 10.7 18.8 6 29 6s18.2 4.7 24.5 15C47.2 31.3 39.2 36 29 36S10.8 31.3 4.5 21Z"
          fill="none"
          stroke="url(#xianwen-brand-gradient)"
          strokeWidth="4.2"
          strokeLinecap="round"
        />
        <circle cx="29" cy="21" r="9" fill="none" stroke="url(#xianwen-brand-gradient)" strokeWidth="4" />
        <circle cx="25.3" cy="21" r="1.35" fill="url(#xianwen-brand-gradient)" />
        <circle cx="29" cy="21" r="1.35" fill="url(#xianwen-brand-gradient)" />
        <circle cx="32.7" cy="21" r="1.35" fill="url(#xianwen-brand-gradient)" />
      </svg>
      <span className={styles.brandName}>显问</span>
      <span className={styles.brandAi}>AI</span>
    </Link>
  );
}

export default function LoginPage() {
  const [form] = Form.useForm<LoginValues>();
  const router = useRouter();
  const sms = useSmsCode("login");
  const [mode, setMode] = useState<LoginMode>("password");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [adminLoginRequired, setAdminLoginRequired] = useState(false);
  const resetComplete = useSyncExternalStore(
    () => () => undefined,
    () => new URLSearchParams(window.location.search).get("reset") === "success",
    () => false,
  );

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

  const submit = async (values: LoginValues) => {
    setError("");
    setAdminLoginRequired(false);
    setSubmitting(true);
    try {
      const user =
        mode === "password"
          ? await loginWithPassword(values.phone, values.password || "")
          : await loginWithSms(values.phone, values.smsCode || "");
      router.push(
        user.approval_status === "pending" ? "/workspace?account=pending" : user.home_route,
      );
    } catch (reason) {
      setAdminLoginRequired(
        reason instanceof AuthApiError && reason.code === "ADMIN_LOGIN_REQUIRED",
      );
      setError(userMessage(reason));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <ConfigProvider
      locale={zhCN}
      theme={{
        token: {
          colorPrimary: "#3569e8",
          borderRadius: 14,
          controlHeightLG: 50,
          fontSize: 15,
        },
      }}
    >
      <main className={styles.page}>
        <div className={styles.glowOne} aria-hidden />
        <div className={styles.glowTwo} aria-hidden />
        <div className={styles.grid} aria-hidden />

        <header className={styles.header}>
          <BrandLogo />
        </header>

        <section className={styles.center} aria-labelledby="login-title">
          <div className={styles.heading}>
            <span className={styles.kicker}>XIANWEN AI</span>
            <h1 id="login-title" className={styles.title}>
              显问 AI GEO 优化系统
            </h1>
            <p className={styles.subtitle}>登录后进入你的 GEO 工作台</p>
          </div>

          <div className={styles.card}>
            <div className={styles.cardHeader}>
              <div>
                <strong>账号登录</strong>
                <span>{mode === "password" ? "使用账号密码登录" : "使用短信验证码登录"}</span>
              </div>
              <Button
                type="text"
                size="small"
                className={styles.modeButton}
                icon={<MessageOutlined />}
                onClick={() => {
                  setMode((current) => (current === "password" ? "sms" : "password"));
                  setError("");
                }}
              >
                {mode === "password" ? "短信登录" : "密码登录"}
              </Button>
            </div>

            {resetComplete && (
              <Alert type="success" showIcon message="密码已重置，请使用新密码登录" />
            )}
            {error && <Alert type="error" showIcon message={error} role="alert" />}
            {adminLoginRequired && (
              <Alert
                type="info"
                showIcon
                message={<Link href="/admin/login">该账号请使用管理员安全登录</Link>}
              />
            )}

            <Form
              form={form}
              layout="vertical"
              requiredMark={false}
              onFinish={submit}
              onFinishFailed={focusFirstInvalidField(form)}
              disabled={submitting}
              className={styles.form}
            >
              <Form.Item name="phone" rules={phoneRules}>
                <Input
                  prefix={<UserOutlined className={styles.inputIcon} />}
                  inputMode="tel"
                  autoComplete="tel"
                  placeholder="手机号 / 账号"
                  size="large"
                  aria-label="手机号或账号"
                />
              </Form.Item>

              {mode === "password" ? (
                <Form.Item
                  name="password"
                  rules={[{ required: true, message: "请输入密码" }]}
                >
                  <Input.Password
                    prefix={<LockOutlined className={styles.inputIcon} />}
                    autoComplete="current-password"
                    placeholder="密码"
                    size="large"
                    aria-label="密码"
                  />
                </Form.Item>
              ) : (
                <SmsCodeField
                  form={form}
                  send={sms.send}
                  sending={sms.sending}
                  remaining={sms.remaining}
                  onError={setError}
                />
              )}

              <div className={styles.formMeta}>
                <Link href="/forgot-password">忘记密码？</Link>
              </div>

              <Button
                type="primary"
                htmlType="submit"
                loading={submitting}
                block
                size="large"
                className={styles.submit}
              >
                登录
              </Button>
            </Form>

            <div className={styles.registerLine}>
              <span>还没有账号？</span>
              <Link href="/register">立即注册</Link>
            </div>
          </div>
        </section>

        <footer className={styles.footer}>© 显问AI 广州显问网络科技有限公司</footer>
      </main>
    </ConfigProvider>
  );
}
