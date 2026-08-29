import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const JUEJIN_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "juejin",
  editorUrl: "https://juejin.cn/editor/drafts/new?v=2",
  authCookieNames: ["sessionid"],
  loginMarkers: ["login"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[placeholder*="标题"]', 'textarea[placeholder*="标题"]'],
  contentSelectors: ['.CodeMirror textarea', '.bytemd-editor textarea', 'textarea[placeholder*="正文"]', '[contenteditable="true"]'],
  titleLimit: 80,
  tagStrategy: {
    required: true,
    phase: "publish_dialog",
    triggerSelectors: ['button:has-text("添加标签")', '[class*="tag"]:has-text("添加")'],
    inputSelectors: ['input[placeholder*="搜索标签"]', 'input[placeholder*="标签"]'],
    maxTags: 3,
    waitAfterEachMs: 700,
  },
  draft: {
    autoSaveWaitMs: 5000,
    successSelectors: ['[class*="status"]:has-text("已保存")', '[class*="save"]:has-text("已保存")'],
    successTexts: ["草稿已保存", "已自动保存", "保存成功"],
    urlPatterns: [/^https:\/\/juejin\.cn\/editor\/drafts\/(?!new(?:[/?#]|$))[^/?#]+/i],
  },
  publishSteps: [
    { name: "open_publish_settings", selectors: ['button:has-text("发布")'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ['button:has-text("确定发布")', 'button:has-text("确认发布")'], optional: true, waitAfterMs: 1000 },
  ],
  successTexts: ["发布成功", "文章发布成功"],
  reviewTexts: ["审核中", "待审核"],
  failureTexts: ["发布失败", "审核不通过", "内容不符合规范"],
  validationTexts: ["请选择分类", "请添加标签", "请选择标签", "请填写必填项"],
  publicLinkSelectors: ['a[href*="juejin.cn/post/"]', 'a[href^="/post/"]'],
  statusItemSelectors: ['tr', 'li', '[class*="article-item"]', '[class*="content-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href^="/post/"]'],
  publicUrlPatterns: [/^https:\/\/juejin\.cn\/post\/\d+/i],
  statusUrlPatterns: [
    /^https:\/\/juejin\.cn\/editor\/drafts\//i,
    /^https:\/\/juejin\.cn\/creator\/(?:content|article)/i,
  ],
  allowedHostSuffixes: ["juejin.cn"],
  resultTimeoutMs: 15_000,
};

export class JuejinPublisher extends BrowserFormPublisher {
  constructor() {
    super(JUEJIN_PUBLISHER_CONFIG);
  }
}
