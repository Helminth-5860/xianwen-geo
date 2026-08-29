import { withPublishPermit } from "../concurrency.js";
import { BaijiahaoPublisher } from "./baijiahao.js";
import { BilibiliPublisher } from "./bilibili.js";
import { CnblogsPublisher } from "./cnblogs.js";
import { CsdnPublisher } from "./csdn.js";
import { DoubanPublisher } from "./douban.js";
import { JianshuPublisher } from "./jianshu.js";
import { JuejinPublisher } from "./juejin.js";
import { OschinaPublisher } from "./oschina.js";
import { QqPublisher } from "./qq.js";
import { SegmentfaultPublisher } from "./segmentfault.js";
import { DouyinImagePublisher, XiaohongshuPublisher } from "./social-image.js";
import { SohuPublisher } from "./sohu.js";
import { ToutiaoPublisher } from "./toutiao.js";
import { WeiboPublisher } from "./weibo.js";
import { WechatPublisher } from "./wechat.js";
import { ZhihuPublisher } from "./zhihu.js";
import type { PlatformPublisher } from "./types.js";

type PublishingCapability = "auth" | "draft" | "public_publish" | "image_upload";

const implementedCapabilities: Readonly<Record<string, readonly PublishingCapability[]>> = {
  wechat: ["auth", "draft", "public_publish", "image_upload"],
  toutiao: ["auth", "draft", "public_publish", "image_upload"],
  baijiahao: ["auth", "draft", "public_publish", "image_upload"],
  zhihu: ["auth", "draft", "public_publish"],
  xiaohongshu: ["auth", "draft", "public_publish", "image_upload"],
  douyin: ["auth", "draft", "public_publish", "image_upload"],
  weibo: ["auth", "draft", "public_publish"],
  bilibili: ["auth", "draft", "public_publish"],
  qq: ["auth", "draft", "public_publish"],
  sohu: ["auth", "draft", "public_publish"],
  csdn: ["auth", "draft", "public_publish"],
  juejin: ["auth", "draft", "public_publish"],
  cnblogs: ["auth", "draft", "public_publish"],
  oschina: ["auth", "draft", "public_publish"],
  segmentfault: ["auth", "draft", "public_publish"],
  jianshu: ["auth", "draft", "public_publish"],
  douban: ["auth", "draft", "public_publish"],
};

const verificationVariables: Readonly<Record<PublishingCapability, string>> = {
  auth: "PUBLISHING_WORKER_VERIFIED_AUTH_PLATFORM_KEYS",
  draft: "PUBLISHING_WORKER_VERIFIED_DRAFT_PLATFORM_KEYS",
  public_publish: "PUBLISHING_WORKER_VERIFIED_PUBLIC_PLATFORM_KEYS",
  image_upload: "PUBLISHING_WORKER_VERIFIED_IMAGE_PLATFORM_KEYS",
};

function configuredKeys(name: string) {
  return new Set(
    (process.env[name] || "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  );
}

function verifiedCapabilities(platformKey: string) {
  const implemented = new Set(implementedCapabilities[platformKey] || []);
  const authAccepted = configuredKeys(verificationVariables.auth).has(platformKey);
  if (!authAccepted || !implemented.has("auth")) return [];
  return (Object.keys(verificationVariables) as PublishingCapability[]).filter((capability) => (
    implemented.has(capability) && configuredKeys(verificationVariables[capability]).has(platformKey)
  ));
}

export function publisherHasVerifiedCapability(
  platformKey: string,
  capability: PublishingCapability,
) {
  return verifiedCapabilities(platformKey).includes(capability);
}

export function validateCapabilityConfiguration() {
  const known = new Set(Object.keys(implementedCapabilities));
  const experimental = configuredKeys("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS");
  const unknownExperimental = [...experimental].filter((key) => !known.has(key) || key === "wechat");
  if (unknownExperimental.length) {
    throw new Error("PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS contains unsupported platform keys");
  }
  for (const [capability, variable] of Object.entries(verificationVariables) as Array<[PublishingCapability, string]>) {
    const configured = configuredKeys(variable);
    const unknown = [...configured].filter((key) => !known.has(key));
    if (unknown.length) throw new Error(`${variable} contains unsupported platform keys`);
    for (const key of configured) {
      if (!(implementedCapabilities[key] || []).includes(capability)) {
        throw new Error(`${variable} contains a capability not implemented by ${key}`);
      }
      if (capability !== "auth" && !configuredKeys(verificationVariables.auth).has(key)) {
        throw new Error(`${variable} requires verified auth for ${key}`);
      }
      if (key !== "wechat" && !experimental.has(key)) {
        throw new Error(`${variable} requires the experimental gate for ${key}`);
      }
    }
  }
}

const publishers: Readonly<Record<string, PlatformPublisher>> = {
  wechat: new WechatPublisher(),
  toutiao: new ToutiaoPublisher(),
  zhihu: new ZhihuPublisher(),
  baijiahao: new BaijiahaoPublisher(),
  xiaohongshu: new XiaohongshuPublisher(),
  douyin: new DouyinImagePublisher(),
  weibo: new WeiboPublisher(),
  bilibili: new BilibiliPublisher(),
  qq: new QqPublisher(),
  sohu: new SohuPublisher(),
  csdn: new CsdnPublisher(),
  juejin: new JuejinPublisher(),
  cnblogs: new CnblogsPublisher(),
  oschina: new OschinaPublisher(),
  segmentfault: new SegmentfaultPublisher(),
  jianshu: new JianshuPublisher(),
  douban: new DoubanPublisher(),
};

function boundedPublisher(publisher: PlatformPublisher): PlatformPublisher {
  return {
    platformKey: publisher.platformKey,
    verifiedCapabilities: publisher.verifiedCapabilities,
    checkAuth: (credentials) => withPublishPermit(() => publisher.checkAuth(credentials)),
    publish: (input) => withPublishPermit(() => publisher.publish(input)),
    ...(publisher.checkStatus
      ? { checkStatus: (input) => withPublishPermit(() => publisher.checkStatus!(input)) }
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
    implemented_capabilities: [...(implementedCapabilities[publisher.platformKey] || [])],
    verified_capabilities: verifiedCapabilities(publisher.platformKey),
  }));
}
