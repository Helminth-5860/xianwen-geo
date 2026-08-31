import { describe, expect, it } from "vitest";

import {
  aiModelDisplayName,
  publicPlanBenefitLines,
  safeLocalProductMessage,
  userFacingApiError,
} from "@/lib/product-copy";

describe("普通用户产品文案", () => {
  it("把模型内部名称转换为用户认识的品牌名称", () => {
    expect(aiModelDisplayName("deepseek")).toBe("DeepSeek");
    expect(aiModelDisplayName("qwen")).toBe("千问");
    expect(aiModelDisplayName("hunyuan")).toBe("混元");
    expect(aiModelDisplayName("unknown-model-id")).toBe("AI 平台");
  });

  it("错误提示只说明业务影响和下一步操作", () => {
    expect(userFacingApiError({ code: "IMAGE_PROVIDER_TIMEOUT", status: 503 })).toBe(
      "响应时间较长，本次操作未能完成，请稍后重新尝试。",
    );
    expect(userFacingApiError({ code: "SOME_PRIVATE_DATABASE_ERROR", status: 500 })).toBe(
      "当前服务暂不可用，请稍后重新尝试。",
    );
    expect(safeLocalProductMessage("Provider request failed at worker queue")).toBe(
      "当前操作未能完成，请稍后重新尝试。",
    );
    expect(userFacingApiError({ code: "COMPETITOR_LIMIT_REACHED", status: 409 })).toBe(
      "当前主体最多设置 3 家核心竞品。",
    );
    expect(userFacingApiError({ code: "COMPETITOR_DUPLICATE", status: 409 })).toBe(
      "这家竞品已设置，请勿重复添加。",
    );
    expect(userFacingApiError({ code: "COMPETITOR_IS_SUBJECT", status: 422 })).toBe(
      "不能将当前主体设置为自己的竞品。",
    );
  });

  it("套餐权益只展示用户能理解的已知内容", () => {
    expect(
      publicPlanBenefitLines({
        subject_active_limit: 3,
        max_models_per_detection: 8,
        article_credits: 500,
        video_script_generations: 3,
        runtime_endpoint: "internal-only",
      }),
    ).toEqual(["单次检测最多选择 8 个模型", "500 篇 AI 文章", "3 条视频脚本"]);
  });

  it("套餐权益中的无限额度统一显示为不限", () => {
    const lines = publicPlanBenefitLines({
      article_generations: 9_223_372_036_854_776_000,
    });

    expect(lines).toEqual(["AI 文章不限"]);
    expect(lines.join(" ")).not.toContain("922337");
  });
});
