import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const SEGMENTFAULT_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "segmentfault",
  editorUrl: "https://segmentfault.com/write",
  authCookieNames: ["SFSSID", "PHPSESSID_sf"],
  loginMarkers: ["login", "user/login"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ["#title", 'input[placeholder*="标题"]', 'input[name="title"]'],
  contentSelectors: ['.CodeMirror textarea', 'textarea[name="text"]', 'textarea[placeholder*="正文"]'],
  titleLimit: 100,
  tagStrategy: {
    required: true,
    triggerSelectors: ["#tags-toggle", 'button:has-text("添加标签")'],
    inputSelectors: ['input[placeholder="搜索标签"]', 'input[placeholder*="标签"]'],
    maxTags: 5,
    waitAfterEachMs: 700,
  },
  coverTriggerTexts: ["设置封面", "添加封面"],
  coverInputSelectors: ['input[type="file"][accept*="image"]'],
  draft: {
    autoSaveWaitMs: 5500,
    successSelectors: ['[class*="save"]:has-text("已保存")', '[class*="status"]:has-text("已保存")'],
    successTexts: ["草稿已保存", "已自动保存", "保存成功"],
    urlPatterns: [/^https:\/\/segmentfault\.com\/(?:write\/)?draft\/12\d+/i],
  },
  publishSteps: [
    { name: "open_publish_settings", selectors: ["#publish-toggle", 'button:has-text("发布文章")'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ["#sureSubmitBtn", 'button:has-text("确认发布")', 'button:has-text("发布")'], waitAfterMs: 1000 },
  ],
  successTexts: ["发布成功", "文章发布成功"],
  reviewTexts: ["审核中", "等待审核"],
  failureTexts: ["发布失败", "审核不通过", "内容不符合规范"],
  validationTexts: ["请选择标签", "请添加标签", "请选择文章类型", "请填写必填项"],
  publicLinkSelectors: ['a[href^="/a/"]', 'a[href*="segmentfault.com/a/"]'],
  statusItemSelectors: ['tr', 'li', 'article', '[class*="article-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href^="/a/"]'],
  publicUrlPatterns: [/^https:\/\/segmentfault\.com\/a\/\d+/i],
  statusUrlPatterns: [
    /^https:\/\/segmentfault\.com\/write(?:[/?#]|$)/i,
    /^https:\/\/segmentfault\.com\/(?:write\/)?draft\/\d+/i,
    /^https:\/\/segmentfault\.com\/u\/[^/]+\/articles/i,
  ],
  allowedHostSuffixes: ["segmentfault.com"],
  resultTimeoutMs: 15_000,
};

export class SegmentfaultPublisher extends BrowserFormPublisher {
  constructor() {
    super(SEGMENTFAULT_PUBLISHER_CONFIG);
  }
}
