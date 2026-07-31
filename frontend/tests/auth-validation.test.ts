import { describe, expect, it } from "vitest";

import {
  normalizedMainlandPhone,
  validateConfirmation,
  validatePassword,
  validatePhone,
} from "../lib/auth-validation";

describe("认证表单校验", () => {
  it("接受并规范识别等价格式手机号", () => {
    expect(normalizedMainlandPhone("0086 138-0013-8000")).toBe("13800138000");
    expect(normalizedMainlandPhone("+8613800138000")).toBe("13800138000");
  });

  it("拒绝无效手机号和过短密码", async () => {
    await expect(validatePhone("123")).rejects.toThrow("中国大陆手机号");
    await expect(validatePassword("short")).rejects.toThrow("10 个字符");
  });

  it("确认密码必须一致", async () => {
    await expect(validateConfirmation("password-a", "password-b")).rejects.toThrow("不一致");
    await expect(validateConfirmation("same-password", "same-password")).resolves.toBeUndefined();
  });
});
