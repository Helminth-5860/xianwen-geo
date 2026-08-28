import { withPublishPermit } from "../concurrency.js";
import { BaijiahaoPublisher } from "./baijiahao.js";
import { BROWSER_PUBLISHER_CONFIGS } from "./browser-configs.js";
import { BrowserFormPublisher } from "./browser-form.js";
import { DouyinImagePublisher, XiaohongshuPublisher } from "./social-image.js";
import { ToutiaoPublisher } from "./toutiao.js";
import { WechatPublisher } from "./wechat.js";
import { ZhihuPublisher } from "./zhihu.js";
import type { PlatformPublisher } from "./types.js";

const browserPublishers = Object.fromEntries(
  Object.entries(BROWSER_PUBLISHER_CONFIGS).map(([key, config]) => [key, new BrowserFormPublisher(config)]),
) as Record<string, PlatformPublisher>;

const publishers: Readonly<Record<string, PlatformPublisher>> = {
  ...browserPublishers,
  wechat: new WechatPublisher(),
  toutiao: new ToutiaoPublisher(),
  zhihu: new ZhihuPublisher(),
  baijiahao: new BaijiahaoPublisher(),
  xiaohongshu: new XiaohongshuPublisher(),
  douyin: new DouyinImagePublisher(),
};

function boundedPublisher(publisher: PlatformPublisher): PlatformPublisher {
  return {
    platformKey: publisher.platformKey,
    verifiedCapabilities: publisher.verifiedCapabilities,
    checkAuth: (credentials) => publisher.checkAuth(credentials),
    publish: (input) => withPublishPermit(() => publisher.publish(input)),
    ...(publisher.checkStatus
      ? { checkStatus: (input) => publisher.checkStatus!(input) }
      : {}),
  };
}

export function getPublisher(platformKey: string) {
  const publisher = publishers[platformKey];
  return publisher ? boundedPublisher(publisher) : null;
}

export function publisherCapabilities() {
  return Object.values(publishers).map((publisher) => ({
    platform_key: publisher.platformKey,
    verified_capabilities: [...publisher.verifiedCapabilities],
  }));
}
