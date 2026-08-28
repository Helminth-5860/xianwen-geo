import { LOGIN_PLATFORMS } from "./platforms.js";
import { publisherCapabilities } from "./publishers/index.js";

const expected = new Set([
  "wechat",
  "toutiao",
  "baijiahao",
  "zhihu",
  "xiaohongshu",
  "weibo",
  "bilibili",
  "douyin",
  "qq",
  "sohu",
  "csdn",
  "juejin",
  "cnblogs",
  "oschina",
  "segmentfault",
  "jianshu",
  "douban",
]);

const publisherKeys = publisherCapabilities().map((item) => item.platform_key);
const publisherSet = new Set(publisherKeys);
if (publisherKeys.length !== 17 || publisherSet.size !== 17) {
  throw new Error(`publisher_catalog_count_mismatch:${publisherKeys.join(",")}`);
}
for (const key of expected) {
  if (!publisherSet.has(key)) throw new Error(`publisher_missing:${key}`);
}
for (const key of publisherSet) {
  if (!expected.has(key)) throw new Error(`unexpected_publisher:${key}`);
}

const loginKeys = Object.keys(LOGIN_PLATFORMS);
const loginSet = new Set(loginKeys);
if (loginKeys.length !== 16 || loginSet.size !== 16) {
  throw new Error(`login_catalog_count_mismatch:${loginKeys.join(",")}`);
}
if (loginSet.has("wechat")) {
  throw new Error("wechat_must_use_official_authorization");
}
for (const key of expected) {
  if (key === "wechat") continue;
  if (!loginSet.has(key)) throw new Error(`browser_login_missing:${key}`);
}

console.log("publishing catalog OK: 17 publishers, 16 browser login flows, 1 official WeChat flow");
