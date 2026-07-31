import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));

import ForgotPasswordPage from "../app/forgot-password/page";
import LoginPage, { LOGIN_MODE_OPTIONS } from "../app/login/page";
import RegisterPage from "../app/register/page";

describe("认证页面", () => {
  it("渲染注册页必需字段和待审核说明", () => {
    const html = renderToStaticMarkup(<RegisterPage />);
    expect(html).toContain("创建账号");
    expect(html).toContain("手机号");
    expect(html).toContain("昵称");
    expect(html).toContain("短信验证码");
    expect(html).toContain("账号审核通过前");
  });

  it("登录页提供密码和短信两种模式", () => {
    const html = renderToStaticMarkup(<LoginPage />);
    expect(LOGIN_MODE_OPTIONS.map((option) => option.label)).toEqual(["密码登录", "短信登录"]);
    expect(html).toContain("密码登录");
    expect(html).toContain("短信登录");
    expect(html).toContain("忘记密码");
  });

  it("忘记密码页说明旧会话失效", () => {
    const html = renderToStaticMarkup(<ForgotPasswordPage />);
    expect(html).toContain("重置登录密码");
    expect(html).toContain("所有旧登录会话都会失效");
    expect(html).toContain("确认新密码");
  });
});
