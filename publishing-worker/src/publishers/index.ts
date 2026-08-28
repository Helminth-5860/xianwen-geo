import { BROWSER_PUBLISHER_CONFIGS } from "./browser-configs.js";
import { BrowserFormPublisher } from "./browser-form.js";
import { ZhihuPublisher } from "./zhihu.js";
import type { PlatformPublisher } from "./types.js";

const browserPublishers = Object.fromEntries(
  Object.entries(BROWSER_PUBLISHER_CONFIGS).map(([key, config]) => [key, new BrowserFormPublisher(config)]),
) as Record<string, PlatformPublisher>;

const publishers: Readonly<Record<string, PlatformPublisher>> = {
  ...browserPublishers,
  // 专用实现覆盖通用候选实现。知乎当前只验证到授权 + 草稿，公开发布仍保持关闭。
  zhihu: new ZhihuPublisher(),
};

export function getPublisher(platformKey: string) {
  return publishers[platformKey] ?? null;
}

export function publisherCapabilities() {
  return Object.values(publishers).map((publisher) => ({
    platform_key: publisher.platformKey,
    verified_capabilities: [...publisher.verifiedCapabilities],
  }));
}
