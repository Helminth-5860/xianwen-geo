import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const CSDN_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "csdn",
  editorUrl: "https://mp.csdn.net/mp_blog/creation/editor",
  authCookieNames: ["UserToken", "UserSecret"],
  loginMarkers: ["login", "passport"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[placeholder*="标题"]', 'textarea[placeholder*="标题"]'],
  contentSelectors: ['.CodeMirror textarea', 'textarea[placeholder*="正文"]', '.ProseMirror[contenteditable="true"]', '[contenteditable="true"]'],
  titleLimit: 100,
  tagStrategy: {
    required: true,
    phase: "publish_dialog",
    inputSelectors: ['input[placeholder*="标签"]', 'input[placeholder*="添加标签"]'],
    maxTags: 5,
  },
  coverTriggerTexts: ["添加封面", "上传封面"],
  coverInputSelectors: ['input[type="file"][accept*="image"]'],
  draft: {
    actionSelectors: ['button:has-text("保存草稿")', 'button:has-text("保存至草稿箱")', 'button:has-text("保存")'],
    successSelectors: ['[class*="toast"]:has-text("保存成功")', '[class*="message"]:has-text("保存成功")'],
    successTexts: ["保存草稿成功", "草稿保存成功", "已保存至草稿箱"],
    urlPatterns: [/^https:\/\/mp\.csdn\.net\/mp_blog\/creation\/editor\/\d+/i],
  },
  publishSteps: [
    { name: "open_publish_settings", selectors: ['button:has-text("发布文章")', 'button:has-text("发布")'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ['button:has-text("确认发布")', 'button:has-text("确定发布")'], optional: true, waitAfterMs: 1000 },
  ],
  successTexts: ["文章发布成功", "发布成功"],
  reviewTexts: ["审核中", "待审核"],
  failureTexts: ["发布失败", "审核不通过", "文章违规", "提交失败"],
  validationTexts: ["请选择文章类型", "请选择分类", "请添加标签", "请填写必填项"],
  publicLinkSelectors: ['a[href*="blog.csdn.net/"][href*="/article/details/"]'],
  statusItemSelectors: ['tr', 'li', '[class*="article-item"]', '[class*="content-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href*="/article/details/"]'],
  publicUrlPatterns: [/^https:\/\/blog\.csdn\.net\/[^/?#]+\/article\/details\/\d+/i],
  statusUrlPatterns: [
    /^https:\/\/mp\.csdn\.net\/mp_blog\/(?:creation\/editor|manage\/article)/i,
    /^https:\/\/editor\.csdn\.net\/(?:md|html|blog)(?:[/?#]|$)/i,
  ],
  allowedHostSuffixes: ["csdn.net"],
  resultTimeoutMs: 15_000,
};

export class CsdnPublisher extends BrowserFormPublisher {
  constructor() {
    super(CSDN_PUBLISHER_CONFIG);
  }
}
