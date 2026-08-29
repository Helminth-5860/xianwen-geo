import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const OSCHINA_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "oschina",
  editorUrl: "https://my.oschina.net/blog/write",
  authCookieNames: ["_user_token"],
  loginMarkers: ["login", "hash_login"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[placeholder*="标题"]', 'input[name*="title"]', 'textarea[placeholder*="标题"]'],
  contentSelectors: ['.CodeMirror textarea', 'textarea[placeholder*="正文"]', '.ProseMirror[contenteditable="true"]', '[contenteditable="true"]'],
  titleLimit: 100,
  tagStrategy: {
    inputSelectors: ['input[placeholder*="标签"]', 'input[placeholder*="搜索标签"]'],
    maxTags: 5,
  },
  draft: {
    actionSelectors: ['button:has-text("保存草稿")', 'button:has-text("存草稿")', 'button:has-text("保存")'],
    successSelectors: ['[class*="message"]:has-text("保存成功")', '[class*="toast"]:has-text("保存成功")'],
    successTexts: ["草稿保存成功", "保存成功", "已保存到草稿箱"],
    urlPatterns: [/^https:\/\/my\.oschina\.net\/(?:u\/\d+\/)?blog\/(?:write|edit)\?.*(?:id|blogId)=\d+/i],
  },
  publishSteps: [
    { name: "publish_blog", selectors: ['button:has-text("发布")', 'button:has-text("提交")'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ['button:has-text("确认发布")', 'button:has-text("确定发布")'], optional: true, waitAfterMs: 1000 },
  ],
  successTexts: ["发布成功", "提交成功"],
  reviewTexts: ["审核中", "待审核"],
  failureTexts: ["发布失败", "提交失败", "审核不通过", "内容违规"],
  validationTexts: ["请选择分类", "请选择博客类型", "请填写必填项"],
  publicLinkSelectors: ['a[href*="my.oschina.net/"][href*="/blog/"]'],
  statusItemSelectors: ['tr', 'li', '[class*="blog-item"]', '[class*="article-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href*="/blog/"]'],
  publicUrlPatterns: [/^https:\/\/my\.oschina\.net\/[^/?#]+\/blog\/\d+/i],
  statusUrlPatterns: [
    /^https:\/\/my\.oschina\.net\/(?:u\/\d+\/)?blog\/(?:write|edit)/i,
    /^https:\/\/my\.oschina\.net\/(?:space\/blog\/manage|blog\/manage)/i,
  ],
  allowedHostSuffixes: ["oschina.net"],
  resultTimeoutMs: 15_000,
};

export class OschinaPublisher extends BrowserFormPublisher {
  constructor() {
    super(OSCHINA_PUBLISHER_CONFIG);
  }
}
