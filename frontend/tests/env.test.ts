import { describe, expect, it } from "vitest";

import { readPublicEnvironment } from "../lib/env";

describe("前端环境配置", () => {
  it("local 使用安全开发默认值", () => {
    expect(readPublicEnvironment({})).toEqual({
      appEnvironment: "local",
      apiBaseUrl: "http://localhost:8000/api/v1",
    });
  });

  it("production 要求显式 HTTPS API 地址", () => {
    expect(() => readPublicEnvironment({ NEXT_PUBLIC_APP_ENV: "production" })).toThrow(
      "NEXT_PUBLIC_API_BASE_URL",
    );
    expect(() =>
      readPublicEnvironment({
        NEXT_PUBLIC_APP_ENV: "production",
        NEXT_PUBLIC_API_BASE_URL: "http://api.example.com/api/v1",
      }),
    ).toThrow("HTTPS");
  });

  it("拒绝使用 NEXT_PUBLIC_ 暴露秘密", () => {
    expect(() =>
      readPublicEnvironment({
        NEXT_PUBLIC_APP_ENV: "local",
        NEXT_PUBLIC_API_KEY: "should-never-be-public",
      }),
    ).toThrow("不得作为前端公开变量");
  });
});
