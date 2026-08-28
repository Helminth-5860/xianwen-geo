import { ZhihuPublisher } from "./zhihu.js";
import type { PlatformPublisher } from "./types.js";

const publishers: Readonly<Record<string, PlatformPublisher>> = {
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
