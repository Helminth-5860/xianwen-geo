import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const JIANSHU_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "jianshu",
  editorUrl: "https://www.jianshu.com/writer#/",
  authCookieNames: ["remember_user_token"],
  loginMarkers: ["sign_in", "login"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[placeholder*="标题"]', 'textarea[placeholder*="标题"]', 'input[name="title"]'],
  contentSelectors: ['.CodeMirror textarea', 'textarea[placeholder*="正文"]', '.ProseMirror[contenteditable="true"]', '[contenteditable="true"]'],
  titleLimit: 100,
  draft: {
    autoSaveWaitMs: 5000,
    successSelectors: ['[class*="save"]:has-text("已保存")', '[class*="status"]:has-text("已保存")'],
    successTexts: ["已自动保存", "文章已保存", "保存成功"],
    urlPatterns: [/^https:\/\/www\.jianshu\.com\/writer#\/notebooks\/[^/]+\/notes\/[^/?#]+/i],
  },
  publishSteps: [
    { name: "open_publish", selectors: ['button:has-text("发布文章")', 'a:has-text("发布文章")', 'button:has-text("发布")'], waitAfterMs: 900 },
    { name: "confirm_publish", selectors: ['button:has-text("确认发布")', 'button:has-text("确定发布")'], optional: true, waitAfterMs: 900 },
  ],
  successTexts: ["发布成功", "文章发布成功"],
  reviewTexts: ["审核中", "等待审核"],
  failureTexts: ["发布失败", "审核不通过", "文章被锁定"],
  validationTexts: ["请选择文集", "请完善发布设置", "请填写必填项"],
  publicLinkSelectors: ['a[href^="/p/"]', 'a[href*="jianshu.com/p/"]'],
  statusItemSelectors: ['li', 'article', '[class*="note-item"]', '[class*="article-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href^="/p/"]'],
  publicUrlPatterns: [/^https:\/\/(?:www\.)?jianshu\.com\/p\/[A-Za-z0-9]+/i],
  statusUrlPatterns: [/^https:\/\/www\.jianshu\.com\/writer(?:[/?#]|$)/i],
  allowedHostSuffixes: ["jianshu.com"],
  resultTimeoutMs: 15_000,
};

export class JianshuPublisher extends BrowserFormPublisher {
  constructor() {
    super(JIANSHU_PUBLISHER_CONFIG);
  }
}
