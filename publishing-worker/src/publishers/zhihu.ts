import type { Page } from "playwright";

import { createPublisherBrowserContext } from "./browser-context.js";
import type {
  PlatformCredentials,
  PlatformPublisher,
  PublicationInput,
  PublicationResult,
  PublicationStatusInput,
  PublicationStatusResult,
} from "./types.js";

const experimental = () => new Set(
  (process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS || "").split(",").map((item) => item.trim().toLowerCase()).filter(Boolean),
).has("zhihu");

const cookieHeader = (credentials: PlatformCredentials) =>
  (credentials.cookies || []).map((cookie) => `${cookie.name}=${cookie.value}`).join("; ");

const commonHeaders = (credentials: PlatformCredentials) => ({
  Cookie: cookieHeader(credentials),
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
  "X-Requested-With": "fetch",
});

const transformHtml = (html: string) =>
  html
    .replace(/<img([^>]+)src="([^"]+)"([^>]*)>/gi, '<figure><img$1src="$2"$3></figure>')
    .replace(/<pre><code class="language-(\w+)">/gi, '<pre lang="$1"><code>')
    .replace(/\s*data-(?!draft)[a-z-]+="[^"]*"/gi, "")
    .replace(/\s*style="[^"]*"/gi, "");

function normalizedText(value: string) {
  return value
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;|&#160;/gi, " ")
    .replace(/&amp;/gi, "&")
    .replace(/&quot;|&#34;/gi, '"')
    .replace(/&#39;|&apos;/gi, "'")
    .replace(/\s+/g, "")
    .trim();
}

export function isZhihuAuthOrRiskUrl(value: string) {
  try {
    const url = new URL(value);
    const marker = `${url.hostname}${url.pathname}${url.search}`.toLowerCase();
    return ["signin", "login", "account/unhuman", "captcha", "challenge", "security", "risk"].some(
      (part) => marker.includes(part),
    );
  } catch {
    return true;
  }
}

export function isZhihuPublicUrlForArticle(value: string, articleId: string) {
  if (!/^\d+$/.test(articleId)) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.hostname === "zhuanlan.zhihu.com"
      && url.pathname === `/p/${articleId}`;
  } catch {
    return false;
  }
}

function isZhihuEditUrlForArticle(value: string, articleId: string) {
  if (!/^\d+$/.test(articleId)) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.hostname === "zhuanlan.zhihu.com"
      && url.pathname === `/p/${articleId}/edit`;
  } catch {
    return false;
  }
}

export function hasZhihuArticleEvidence(htmlOrText: string, articleId: string, expectedTitle: string | undefined) {
  if (!/^\d+$/.test(articleId) || !expectedTitle?.trim()) return false;
  const text = normalizedText(htmlOrText);
  const title = normalizedText(expectedTitle);
  if (!title || !text.includes(title)) return false;
  const lower = htmlOrText.toLowerCase();
  return ![
    "页面不存在",
    "内容不存在",
    "登录后继续",
    "安全验证",
    "访问异常",
    "unhuman",
    "captcha",
  ].some((value) => lower.includes(value));
}

async function verifyZhihuDraft(
  credentials: PlatformCredentials,
  draftId: string,
  expectedTitle: string,
  expectedContent: string,
) {
  const response = await fetch(`https://zhuanlan.zhihu.com/api/articles/${encodeURIComponent(draftId)}/draft`, {
    headers: commonHeaders(credentials),
    redirect: "error",
    signal: AbortSignal.timeout(20_000),
  });
  if (!response.ok) return false;
  const draft = (await response.json()) as { id?: string | number; title?: string; content?: string };
  if (String(draft.id || "") !== draftId || normalizedText(draft.title || "") !== normalizedText(expectedTitle)) return false;
  const expected = normalizedText(expectedContent).slice(0, 48);
  return Boolean(expected) && normalizedText(draft.content || "").includes(expected);
}

async function zhihuEditorMatches(page: Page, expectedTitle: string, expectedContent: string) {
  const title = page.locator('textarea[placeholder*="标题"], input[placeholder*="标题"]').first();
  const editor = page.locator('div[contenteditable="true"], .public-DraftEditor-content').first();
  if (!(await title.isVisible({ timeout: 4_000 }).catch(() => false))) return false;
  if (!(await editor.isVisible({ timeout: 4_000 }).catch(() => false))) return false;
  const actualTitle = await title.inputValue().catch(async () => (await title.textContent().catch(() => "")) || "");
  const actualContent = await editor.innerText().catch(() => "");
  const expectedSnippet = normalizedText(expectedContent).slice(0, 48);
  return normalizedText(actualTitle) === normalizedText(expectedTitle)
    && Boolean(expectedSnippet)
    && normalizedText(actualContent).includes(expectedSnippet);
}

export class ZhihuPublisher implements PlatformPublisher {
  readonly platformKey = "zhihu";
  // 当前代码路径只把“授权检查 + 草稿创建”列为已验证目标；公开发布必须真实账号验收后再开放。
  readonly verifiedCapabilities = ["auth", "draft"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    const cookie = cookieHeader(credentials);
    if (!cookie) return { ok: false };
    try {
      const response = await fetch("https://www.zhihu.com/api/v4/me", {
        headers: commonHeaders(credentials),
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) return { ok: false };
      const data = (await response.json()) as { id?: string; name?: string };
      return data.id
        ? { ok: true, displayName: data.name || "", externalAccountId: data.id }
        : { ok: false };
    } catch {
      return { ok: false };
    }
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    const urlArticleId = input.managementUrl?.match(/\/p\/(\d+)(?:\/edit)?(?:[/?#]|$)/)?.[1] || "";
    const articleId = input.externalPostId || urlArticleId;
    if (!/^\d+$/.test(articleId) || (input.externalPostId && urlArticleId && input.externalPostId !== urlArticleId)) {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };
    }
    const publicUrl = `https://zhuanlan.zhihu.com/p/${encodeURIComponent(articleId)}`;
    try {
      const response = await fetch(publicUrl, {
        headers: commonHeaders(input.credentials),
        redirect: "follow",
        signal: AbortSignal.timeout(20_000),
      });
      if (response.status === 401 || response.status === 403 || isZhihuAuthOrRiskUrl(response.url)) {
        return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      if (response.ok && isZhihuPublicUrlForArticle(response.url, articleId)) {
        const html = (await response.text()).slice(0, 200_000);
        if (hasZhihuArticleEvidence(html, articleId, input.expectedTitle)) {
          return { platformKey: this.platformKey, status: "published", publicUrl, managementUrl: input.managementUrl };
        }
      }
      return { platformKey: this.platformKey, status: "submitted", managementUrl: input.managementUrl };
    } catch {
      return { platformKey: this.platformKey, status: "unknown", managementUrl: input.managementUrl, safeErrorCode: "platform_unavailable" };
    }
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    const auth = await this.checkAuth(input.credentials);
    if (!auth.ok) {
      return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    if (input.publishMode === "public" && !experimental()) {
      return {
        success: false,
        platformKey: this.platformKey,
        status: "action_required",
        safeErrorCode: "public_publish_not_verified",
      };
    }

    try {
      const createResponse = await fetch("https://zhuanlan.zhihu.com/api/articles/drafts", {
        method: "POST",
        headers: {
          ...commonHeaders(input.credentials),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: input.title, content: "", delta_time: 0 }),
        signal: AbortSignal.timeout(20_000),
      });
      if (!createResponse.ok) {
        return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_rejected" };
      }
      const created = (await createResponse.json()) as { id?: string | number };
      if (!created.id || !/^\d+$/.test(String(created.id))) {
        return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_invalid_response" };
      }
      const draftId = String(created.id);
      const updateResponse = await fetch(`https://zhuanlan.zhihu.com/api/articles/${draftId}/draft`, {
        method: "PATCH",
        headers: {
          ...commonHeaders(input.credentials),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: input.title, content: transformHtml(input.contentHtml) }),
        signal: AbortSignal.timeout(20_000),
      });
      if (!updateResponse.ok) {
        return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_rejected" };
      }
      if (!(await verifyZhihuDraft(input.credentials, draftId, input.title, input.contentText))) {
        return {
          success: false,
          platformKey: this.platformKey,
          status: "action_required",
          externalPostId: draftId,
          managementUrl: `https://zhuanlan.zhihu.com/p/${draftId}/edit`,
          safeErrorCode: "draft_save_unconfirmed",
        };
      }
      const editUrl = `https://zhuanlan.zhihu.com/p/${draftId}/edit`;
      if (input.publishMode === "public") {
        const { browser, context } = await createPublisherBrowserContext(input.credentials);
        try {
          const page = await context.newPage();
          await page.goto(editUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
          await page.waitForTimeout(1_500);
          if (isZhihuAuthOrRiskUrl(page.url())) {
            return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
          }
          const beforePublish = (await page.locator("body").innerText().catch(() => "")).slice(0, 100_000);
          const draftEditorVerified = isZhihuEditUrlForArticle(page.url(), draftId)
            && await zhihuEditorMatches(page, input.title, input.contentText);
          if (isZhihuAuthOrRiskUrl(page.url()) || ["安全验证", "访问异常", "请完成验证"].some((value) => beforePublish.includes(value))) {
            return { success: false, platformKey: this.platformKey, status: "action_required", externalPostId: draftId, safeErrorCode: "publish_result_unconfirmed" };
          }
          if (!draftEditorVerified) {
            return { success: false, platformKey: this.platformKey, status: "action_required", externalPostId: draftId, managementUrl: editUrl, safeErrorCode: "draft_save_unconfirmed" };
          }
          const publish = page.locator('button:has-text("发布文章"), button:has-text("发布")').last();
          if (!(await publish.isVisible({ timeout: 5_000 }).catch(() => false))) {
            return { success: false, platformKey: this.platformKey, status: "action_required", externalPostId: draftId, managementUrl: editUrl, safeErrorCode: "publish_control_changed" };
          }
          await publish.click();
          const dialog = page.locator('[role="dialog"], .Modal-content').filter({ hasText: /发布|确认/ }).last();
          if (await dialog.isVisible({ timeout: 2_000 }).catch(() => false)) {
            const confirm = dialog.locator('button:has-text("确认发布"), button:has-text("发布")').last();
            if (await confirm.isVisible({ timeout: 1_000 }).catch(() => false)) await confirm.click();
          }
          await page.waitForTimeout(5_000);
          const publicUrl = `https://zhuanlan.zhihu.com/p/${draftId}`;
          const body = (await page.locator("body").innerText().catch(() => "")).slice(-30_000);
          if (isZhihuAuthOrRiskUrl(page.url()) || ["安全验证", "访问异常", "请完成验证"].some((value) => body.includes(value))) {
            return { success: false, platformKey: this.platformKey, status: "action_required", externalPostId: draftId, safeErrorCode: "publish_result_unconfirmed" };
          }
          if (["发布失败", "审核不通过", "内容违规"].some((value) => body.includes(value))) {
            return { success: false, platformKey: this.platformKey, status: "failed", externalPostId: draftId, managementUrl: page.url(), safeErrorCode: "content_rejected" };
          }
          if (isZhihuPublicUrlForArticle(page.url(), draftId) && hasZhihuArticleEvidence(body, draftId, input.title)) {
            return { success: true, platformKey: this.platformKey, status: "published", externalPostId: draftId, publicUrl, managementUrl: page.url() };
          }
          if (
            ["发布成功", "审核中", "已提交"].some((value) => body.includes(value))
            && (isZhihuEditUrlForArticle(page.url(), draftId) || isZhihuPublicUrlForArticle(page.url(), draftId))
            && (isZhihuPublicUrlForArticle(page.url(), draftId)
              ? hasZhihuArticleEvidence(body, draftId, input.title)
              : draftEditorVerified)
          ) {
            return { success: true, platformKey: this.platformKey, status: "submitted", externalPostId: draftId, managementUrl: page.url() };
          }
          return { success: false, platformKey: this.platformKey, status: "action_required", externalPostId: draftId, managementUrl: page.url(), safeErrorCode: "publish_result_unconfirmed" };
        } finally {
          await context.close().catch(() => undefined);
          await browser.close().catch(() => undefined);
        }
      }
      return {
        success: true,
        platformKey: this.platformKey,
        status: "drafted",
        externalPostId: draftId,
        editUrl,
        managementUrl: editUrl,
      };
    } catch {
      return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_unavailable" };
    }
  }
}
