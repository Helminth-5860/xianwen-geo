import { BILIBILI_PUBLISHER_CONFIG } from "./bilibili.js";
import type { BrowserPublisherConfig } from "./browser-form.js";
import { CNBLOGS_PUBLISHER_CONFIG } from "./cnblogs.js";
import { CSDN_PUBLISHER_CONFIG } from "./csdn.js";
import { DOUBAN_PUBLISHER_CONFIG } from "./douban.js";
import { JIANSHU_PUBLISHER_CONFIG } from "./jianshu.js";
import { JUEJIN_PUBLISHER_CONFIG } from "./juejin.js";
import { OSCHINA_PUBLISHER_CONFIG } from "./oschina.js";
import { QQ_PUBLISHER_CONFIG } from "./qq.js";
import { SEGMENTFAULT_PUBLISHER_CONFIG } from "./segmentfault.js";
import { SOHU_PUBLISHER_CONFIG } from "./sohu.js";
import { WEIBO_PUBLISHER_CONFIG } from "./weibo.js";

// 这些平台使用各自独立的配置与类；仍须逐个平台通过真实账号验收后才能加入运行时开关。
export const BROWSER_PUBLISHER_CONFIGS: Readonly<Record<string, BrowserPublisherConfig>> = {
  weibo: WEIBO_PUBLISHER_CONFIG,
  bilibili: BILIBILI_PUBLISHER_CONFIG,
  qq: QQ_PUBLISHER_CONFIG,
  sohu: SOHU_PUBLISHER_CONFIG,
  csdn: CSDN_PUBLISHER_CONFIG,
  juejin: JUEJIN_PUBLISHER_CONFIG,
  cnblogs: CNBLOGS_PUBLISHER_CONFIG,
  oschina: OSCHINA_PUBLISHER_CONFIG,
  segmentfault: SEGMENTFAULT_PUBLISHER_CONFIG,
  jianshu: JIANSHU_PUBLISHER_CONFIG,
  douban: DOUBAN_PUBLISHER_CONFIG,
};
