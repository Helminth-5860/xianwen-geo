import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const WEIBO_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "weibo",
  editorUrl: "https://card.weibo.com/article/v5/editor#/draft",
  authCookieNames: ["SUB"],
  loginMarkers: ["login", "signin", "passport"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['textarea[placeholder="请输入标题"]', 'textarea[placeholder*="标题"]'],
  contentSelectors: [".tiptap.ProseMirror", '.ProseMirror[contenteditable="true"]', '[contenteditable="true"]'],
  titleLimit: 40,
  coverTriggerTexts: ["添加封面", "选择封面"],
  coverInputSelectors: ['input[type="file"][accept*="image"]'],
  draft: {
    actionSelectors: ['button:has-text("保存草稿")', 'button:has-text("存草稿")', 'button:has-text("保存")'],
    successSelectors: ['[role="alert"]:has-text("保存成功")', '.toast:has-text("保存成功")'],
    successTexts: ["草稿保存成功", "保存草稿成功", "已保存至草稿箱"],
    urlPatterns: [/^https:\/\/card\.weibo\.com\/article\/v5\/editor#\/draft\/.+/i],
  },
  publishSteps: [
    { name: "open_publish_preview", selectors: ['button:has-text("下一步")'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ['button:has-text("确认发布")', 'button:has-text("发布")'], waitAfterMs: 1200 },
  ],
  successTexts: ["发布成功", "文章发布成功", "创建成功"],
  reviewTexts: ["审核中", "提交审核成功"],
  failureTexts: ["发布失败", "提交失败", "审核不通过", "内容违规"],
  validationTexts: ["请选择封面", "请输入导语", "请完善发布信息", "请填写必填项"],
  publicLinkSelectors: ['a[href*="/ttarticle/p/show"]', 'a[href*="/ttarticle/x/m/show"]'],
  statusItemSelectors: ['tr', 'li', '[class*="draft-item"]', '[class*="article-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href*="/ttarticle/"]'],
  publicUrlPatterns: [
    /^https:\/\/(?:www\.)?weibo\.com\/ttarticle\/p\/show\?id=\d+/i,
    /^https:\/\/(?:www\.)?weibo\.com\/ttarticle\/x\/m\/show\/id\/\d+/i,
  ],
  statusUrlPatterns: [/^https:\/\/card\.weibo\.com\/article\/v5\/(?:editor|manage|draft)/i],
  allowedHostSuffixes: ["weibo.com"],
  resultTimeoutMs: 15_000,
};

export class WeiboPublisher extends BrowserFormPublisher {
  constructor() {
    super(WEIBO_PUBLISHER_CONFIG);
  }
}
