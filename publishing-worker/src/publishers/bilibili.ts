import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const BILIBILI_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "bilibili",
  editorUrl: "https://member.bilibili.com/york/read-editor",
  authCookieNames: ["SESSDATA"],
  loginMarkers: ["login", "passport"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[placeholder*="标题"]', 'textarea[placeholder*="标题"]', 'input[data-placeholder*="标题"]'],
  contentSelectors: ['.ProseMirror[contenteditable="true"]', '[data-slate-editor="true"]', '[contenteditable="true"]'],
  titleLimit: 64,
  coverTriggerTexts: ["自定义封面", "设置封面"],
  coverInputSelectors: ['input[type="file"][accept*="image"]'],
  draft: {
    actionSelectors: ['button:has-text("保存为草稿")', 'button:has-text("存草稿")', 'button:has-text("保存草稿")'],
    successSelectors: ['[class*="toast"]:has-text("保存成功")', '[class*="message"]:has-text("保存成功")'],
    successTexts: ["保存草稿成功", "草稿保存成功", "已保存到草稿箱"],
    urlPatterns: [/^https:\/\/member\.bilibili\.com\/(?:york\/read-editor|platform\/upload\/text\/edit)\?.*(?:id|aid)=\d+/i],
  },
  publishSteps: [
    { name: "submit_article", selectors: ['button:has-text("提交文章")', 'button:has-text("发布")'], waitAfterMs: 1200 },
    { name: "confirm_submit", selectors: ['button:has-text("确认发布")', 'button:has-text("确认提交")'], optional: true, waitAfterMs: 1000 },
  ],
  successTexts: ["发布成功", "投稿成功", "提交成功"],
  reviewTexts: ["审核中", "稿件审核中", "等待审核"],
  failureTexts: ["投稿失败", "发布失败", "审核不通过", "稿件被退回"],
  validationTexts: ["请选择创作声明", "请添加话题", "请完善发布设置", "请填写必填项"],
  publicLinkSelectors: ['a[href*="/read/cv"]', 'a[href*="/opus/"]'],
  statusItemSelectors: ['tr', 'li', '[class*="article-item"]', '[class*="content-card"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href*="/read/cv"]', 'a[href*="/opus/"]'],
  publicUrlPatterns: [
    /^https:\/\/(?:www\.)?bilibili\.com\/read\/cv\d+/i,
    /^https:\/\/(?:www\.)?bilibili\.com\/opus\/\d+/i,
  ],
  statusUrlPatterns: [
    /^https:\/\/member\.bilibili\.com\/york\/read-editor/i,
    /^https:\/\/member\.bilibili\.com\/platform\/(?:upload\/text|manage\/article)/i,
  ],
  allowedHostSuffixes: ["bilibili.com"],
  resultTimeoutMs: 15_000,
};

export class BilibiliPublisher extends BrowserFormPublisher {
  constructor() {
    super(BILIBILI_PUBLISHER_CONFIG);
  }
}
