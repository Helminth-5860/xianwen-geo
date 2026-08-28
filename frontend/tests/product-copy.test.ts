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
  });

  it("套餐权益只展示用户能理解的已知内容", () => {
    expect(
      publicPlanBenefitLines({
        subject_active_limit: 3,
        max_models_per_detection: 8,
        article_credits: 500,
        runtime_endpoint: "internal-only",
      }),
    ).toEqual(["最多管理 3 个主体", "单次检测最多覆盖 8 个 AI 平台", "500 次文章生成"]);
  });
});
