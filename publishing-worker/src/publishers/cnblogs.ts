import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const CNBLOGS_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "cnblogs",
  editorUrl: "https://i.cnblogs.com/posts/edit",
  authCookieNames: [".CNBlogsCookie"],
  loginMarkers: ["signin", "account"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['#Editor_Edit_txbTitle', 'input[name*="txbTitle"]', 'input[placeholder*="标题"]'],
  contentSelectors: ['#Editor_Edit_EditorBody', 'textarea[name*="EditorBody"]', '.CodeMirror textarea', '[contenteditable="true"]'],
  titleLimit: 120,
  tagStrategy: {
    inputSelectors: ['#Editor_Edit_Advanced_txbTag', 'input[name*="txbTag"]', 'input[placeholder*="标签"]'],
    maxTags: 5,
  },
  draft: {
    actionSelectors: ['input[value="存为草稿"]', 'button:has-text("存为草稿")', 'button:has-text("保存草稿")'],
    successSelectors: ['[role="alert"]:has-text("保存成功")', '.alert:has-text("保存成功")'],
    successTexts: ["保存成功", "草稿保存成功"],
    urlPatterns: [/^https:\/\/i\.cnblogs\.com\/posts\/edit\?postId=\d+/i],
  },
  publishSteps: [
    { name: "publish_post", selectors: ['input[value="发布"]', 'button:has-text("发布")'], waitAfterMs: 1000 },
  ],
  successTexts: ["发布成功", "文章发布成功"],
  failureTexts: ["发布失败", "标题重复", "保存失败", "提交失败"],
  validationTexts: ["请选择分类", "标题不能为空", "正文不能为空", "请填写必填项"],
  publicLinkSelectors: ['a[href*="www.cnblogs.com/"][href*="/p/"]', 'a[href*="www.cnblogs.com/"][href*="/articles/"]'],
  statusItemSelectors: ['tr', 'li', '[class*="post-item"]', '[class*="article-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href*="/p/"]', 'a[href*="/articles/"]'],
  publicUrlPatterns: [/^https:\/\/www\.cnblogs\.com\/[^/?#]+\/(?:p|articles)\/\d+\.html/i],
  statusUrlPatterns: [/^https:\/\/i\.cnblogs\.com\/posts\/(?:edit|list)/i],
  allowedHostSuffixes: ["cnblogs.com"],
  resultTimeoutMs: 12_000,
};

export class CnblogsPublisher extends BrowserFormPublisher {
  constructor() {
    super(CNBLOGS_PUBLISHER_CONFIG);
  }
}
