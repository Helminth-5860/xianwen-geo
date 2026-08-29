import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const SOHU_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "sohu",
  editorUrl: "https://mp.sohu.com/mpfe/v3/main/news/addarticle",
  authCookieNames: ["_mp_key"],
  loginMarkers: ["login", "passport"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[placeholder*="标题"]', 'textarea[placeholder*="标题"]', 'input[name*="title"]'],
  contentSelectors: ['.ProseMirror[contenteditable="true"]', '[contenteditable="true"]', 'textarea[placeholder*="正文"]'],
  titleLimit: 64,
  coverTriggerTexts: ["上传封面", "选择封面", "添加封面"],
  coverInputSelectors: ['input[type="file"][accept*="image"]'],
  draft: {
    actionSelectors: ['button:has-text("存草稿")', 'button:has-text("保存草稿")', 'button:has-text("保存")'],
    successSelectors: ['[class*="toast"]:has-text("保存成功")', '[class*="message"]:has-text("保存成功")'],
    successTexts: ["草稿保存成功", "已保存至草稿箱", "保存成功"],
    urlPatterns: [/^https:\/\/mp\.sohu\.com\/mpfe\/v3\/main\/news\/(?:addarticle|edit).*(?:id|newsId)=/i],
  },
  publishSteps: [
    { name: "publish_article", selectors: ['button:has-text("发布")', 'button:has-text("提交")'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ['button:has-text("确认发布")', 'button:has-text("确定发布")'], optional: true, waitAfterMs: 1000 },
  ],
  successTexts: ["发布成功", "提交成功"],
  reviewTexts: ["审核中", "待审核", "已提交审核"],
  failureTexts: ["发布失败", "提交失败", "审核不通过", "已驳回"],
  validationTexts: ["请选择分类", "请选择封面", "请完善发布信息", "请填写必填项"],
  publicLinkSelectors: ['a[href*="www.sohu.com/a/"]', 'a[href*="sohu.com/a/"]'],
  statusItemSelectors: ['tr', 'li', '[class*="article-item"]', '[class*="news-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href*="sohu.com/a/"]'],
  publicUrlPatterns: [/^https:\/\/(?:www\.)?sohu\.com\/a\/\d+_\d+/i],
  statusUrlPatterns: [/^https:\/\/mp\.sohu\.com\/mpfe\/v3\/main\/news\//i],
  allowedHostSuffixes: ["sohu.com"],
  resultTimeoutMs: 15_000,
};

export class SohuPublisher extends BrowserFormPublisher {
  constructor() {
    super(SOHU_PUBLISHER_CONFIG);
  }
}
