"use client";

import { LockOutlined, UserOutlined } from "@ant-design/icons";
import { Alert, Button, ConfigProvider, Form, Input } from "antd";
import zhCN from "antd/locale/zh_CN";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState, useSyncExternalStore } from "react";

import { phoneRules } from "@/components/auth/sms-code-field";
import { getCurrentUser, loginWithPassword, userMessage } from "@/lib/auth-client";
import { focusFirstInvalidField } from "@/lib/form-focus";

import styles from "./login.module.css";
import { officialXianwenLogoDataUrl } from "./logo-data";

type LoginValues = { phone: string; password: string };

export default function LoginPage() {
  const [form] = Form.useForm<LoginValues>();
  const router = useRouter();
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
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
    setSubmitting(true);
    try {
      const user = await loginWithPassword(values.phone, values.password);
      router.push(
        user.approval_status === "pending" ? "/workspace?account=pending" : user.home_route,
      );
    } catch (reason) {
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
          colorPrimary: "#3768f4",
          borderRadius: 12,
          controlHeightLG: 48,
          fontSize: 15,
        },
      }}
    >
      <main className={styles.page}>
        <div className={styles.ambient} aria-hidden />

        <header className={styles.header}>
          <Link href="/login" className={styles.brand} aria-label="显问 AI">
            <img src={officialXianwenLogoDataUrl} alt="显问 AI" className={styles.brandLogo} />
          </Link>
        </header>

        <section className={styles.center} aria-labelledby="login-title">
          <div className={styles.heading}>
            <h1 id="login-title" className={styles.title}>
              显问AI GEO优化系统
            </h1>
          </div>

          <div className={styles.card}>
            {resetComplete && (
              <Alert type="success" showIcon message="密码已重置，请使用新密码登录" />
            )}
            {error && <Alert type="error" showIcon message={error} role="alert" />}

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
                  autoComplete="username"
                  placeholder="手机号 / 账号"
                  size="large"
                  aria-label="手机号或账号"
                />
              </Form.Item>

              <Form.Item name="password" rules={[{ required: true, message: "请输入密码" }]}>
                <Input.Password
                  prefix={<LockOutlined className={styles.inputIcon} />}
                  autoComplete="current-password"
                  placeholder="密码"
                  size="large"
                  aria-label="密码"
                />
              </Form.Item>

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
