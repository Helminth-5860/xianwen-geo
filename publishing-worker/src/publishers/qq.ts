import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const QQ_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "qq",
  editorUrl: "https://om.qq.com/article/articlePublish",
  authCookieNames: ["p_skey"],
  loginMarkers: ["login", "userauth", "passport"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[placeholder*="标题"]', 'textarea[placeholder*="标题"]', 'input[name*="title"]'],
  contentSelectors: ['.ProseMirror[contenteditable="true"]', '[contenteditable="true"]', 'textarea[placeholder*="正文"]'],
  titleLimit: 64,
  coverTriggerTexts: ["选择封面", "添加封面"],
  coverInputSelectors: ['input[type="file"][accept*="image"]'],
  draft: {
    actionSelectors: ['button:has-text("存草稿")', 'button:has-text("保存草稿")', 'button:has-text("保存")'],
    successSelectors: ['[class*="toast"]:has-text("保存成功")', '[class*="message"]:has-text("草稿")'],
    successTexts: ["草稿保存成功", "已保存至草稿箱", "保存成功"],
    urlPatterns: [/^https:\/\/om\.qq\.com\/article\/(?:articlePublish|articleEdit).*(?:id|article_id)=/i],
  },
  publishSteps: [
    { name: "publish_article", selectors: ['button:has-text("发布")', 'button:has-text("提交")'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ['button:has-text("确认发布")', 'button:has-text("确定发布")'], optional: true, waitAfterMs: 1000 },
  ],
  successTexts: ["发布成功", "提交成功"],
  reviewTexts: ["审核中", "待审核", "已提交审核"],
  failureTexts: ["发布失败", "提交失败", "审核不通过", "已驳回"],
  validationTexts: ["请选择分类", "请选择封面", "请完善发布信息", "请填写必填项"],
  publicLinkSelectors: ['a[href*="new.qq.com/rain/a/"]', 'a[href*="page.om.qq.com/page/"]'],
  statusItemSelectors: ['tr', 'li', '[class*="article-item"]', '[class*="content-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href*="article"]'],
  publicUrlPatterns: [
    /^https:\/\/new\.qq\.com\/rain\/a\/[A-Za-z0-9_-]+/i,
    /^https:\/\/page\.om\.qq\.com\/page\/[A-Za-z0-9_-]+/i,
  ],
  statusUrlPatterns: [/^https:\/\/om\.qq\.com\/(?:article|content)\//i],
  allowedHostSuffixes: ["qq.com"],
  resultTimeoutMs: 15_000,
};

export class QqPublisher extends BrowserFormPublisher {
  constructor() {
    super(QQ_PUBLISHER_CONFIG);
  }
}
