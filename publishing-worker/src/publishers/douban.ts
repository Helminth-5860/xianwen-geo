import { BrowserFormPublisher, type BrowserPublisherConfig } from "./browser-form.js";

export const DOUBAN_PUBLISHER_CONFIG: BrowserPublisherConfig = {
  platformKey: "douban",
  editorUrl: "https://www.douban.com/note/create",
  authCookieNames: ["dbcl2"],
  loginMarkers: ["passport", "login"],
  loginSelectors: ['input[type="password"]'],
  titleSelectors: ['input[name="note_title"]', 'input[placeholder*="标题"]'],
  contentSelectors: ['textarea[name="note_text"]', '.ProseMirror[contenteditable="true"]', '[contenteditable="true"]'],
  titleLimit: 100,
  coverTriggerTexts: ["添加图片", "上传图片"],
  coverInputSelectors: ['input[type="file"][accept*="image"]'],
  draft: {
    actionSelectors: ['input[value*="保存草稿"]', 'button:has-text("保存草稿")', 'button:has-text("存草稿")'],
    successSelectors: ['[class*="message"]:has-text("保存成功")', '[class*="toast"]:has-text("保存成功")'],
    successTexts: ["草稿保存成功", "保存草稿成功", "已保存到草稿箱"],
    urlPatterns: [/^https:\/\/www\.douban\.com\/note\/\d+\/edit/i],
  },
  publishSteps: [
    { name: "open_publish_settings", selectors: ['button:has-text("下一步")', 'input[value="下一步"]'], waitAfterMs: 1000 },
    { name: "confirm_publish", selectors: ['button:has-text("发表")', 'input[value*="发表"]', 'button:has-text("发布")'], waitAfterMs: 1000 },
  ],
  successTexts: ["发表成功", "发布成功"],
  reviewTexts: ["审核中", "等待审核"],
  failureTexts: ["发表失败", "发布失败", "审核不通过", "内容不可见"],
  validationTexts: ["请选择权限", "请选择内容说明", "请完善发布设置", "请填写必填项"],
  publicLinkSelectors: ['a[href*="www.douban.com/note/"]', 'a[href^="/note/"]'],
  statusItemSelectors: ['tr', 'li', 'article', '[class*="note-item"]'],
  statusTitleSelectors: ['[class*="title"]', 'a[href^="/note/"]'],
  publicUrlPatterns: [/^https:\/\/www\.douban\.com\/note\/\d+\/?(?:[?#].*)?$/i],
  statusUrlPatterns: [
    /^https:\/\/www\.douban\.com\/note\/(?:create|\d+\/edit)/i,
    /^https:\/\/www\.douban\.com\/mine\/notes/i,
  ],
  allowedHostSuffixes: ["douban.com"],
  resultTimeoutMs: 15_000,
};

export class DoubanPublisher extends BrowserFormPublisher {
  constructor() {
    super(DOUBAN_PUBLISHER_CONFIG);
  }
}
