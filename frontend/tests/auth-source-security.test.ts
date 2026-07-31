import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const ROOT = join(import.meta.dirname, "..");
const browserSources = [
  "lib/auth-client.ts",
  "lib/form-focus.ts",
  "hooks/use-sms-code.ts",
  "app/register/page.tsx",
  "app/login/page.tsx",
  "app/forgot-password/page.tsx",
].map((path) => readFileSync(join(ROOT, path), "utf8"));

describe("浏览器认证安全边界", () => {
  it("不包含 Mock outbox、万能验证码或 localStorage 令牌", () => {
    const combined = browserSources.join("\n").toLowerCase();
    expect(combined).not.toContain("outbox");
    expect(combined).not.toContain("localstorage");
    expect(combined).not.toContain("123456");
  });

  it("所有认证 POST 通过集中客户端发送", () => {
    for (const source of browserSources.slice(3)) {
      expect(source).not.toContain("fetch(");
    }
  });
});
