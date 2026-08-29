import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import type { Page } from "playwright";

import { createPublisherBrowserContext } from "./browser-context.js";

import type {
  PlatformCredentials,
  PlatformPublisher,
  PublicationAsset,
  PublicationInput,
  PublicationResult,
  PublicationStatusInput,
  PublicationStatusResult,
} from "./types.js";

const experimental = () =>
  new Set(
    (process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS || "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  ).has("toutiao");
const editorUrl = "https://mp.toutiao.com/profile_v4/graphic/publish";

async function downloadAsset(asset: PublicationAsset) {
  const response = await fetch(asset.url, { redirect: "follow" });
  if (!response.ok) throw new Error("media_download_failed");
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!bytes.length || bytes.length > 15 * 1024 * 1024) throw new Error("media_invalid");
  const mime = response.headers.get("content-type") || "image/jpeg";
  return { bytes, mime };
}

async function uploadInlineImage(page: Page, asset: PublicationAsset) {
  const { bytes, mime } = await downloadAsset(asset);
  const base64 = bytes.toString("base64");
  return page.evaluate(
    async ({ encoded, contentType }) => {
      const binary = atob(encoded);
      const values = new Uint8Array(binary.length);
      for (let index = 0; index < binary.length; index += 1) values[index] = binary.charCodeAt(index);
      const form = new FormData();
      form.append("image", new Blob([values], { type: contentType }), "article-image.jpg");
      const response = await fetch(
        "https://mp.toutiao.com/spice/image?upload_source=20020003&aid=1231&device_platform=web",
        { method: "POST", body: form, credentials: "include" },
      );
      if (!response.ok) return "";
      const data = (await response.json()) as { code?: number; data?: { image_url?: string } };
      return data.code === 0 && typeof data.data?.image_url === "string" ? data.data.image_url : "";
    },
    { encoded: base64, contentType: mime },
  );
}

function injectImages(contentHtml: string, imageUrls: string[]) {
  if (!imageUrls.length) return contentHtml;
  const imageBlocks = imageUrls.map((url) => `<p><img src="${url}" /></p>`);
  const matches = [...contentHtml.matchAll(/<\/(?:p|h2|h3|blockquote|ul|ol)>/gi)];
  if (!matches.length) return `${contentHtml}${imageBlocks.join("")}`;

  const insertions = imageUrls.map((_, index) => {
    const ordinal = Math.min(
      matches.length - 1,
      Math.max(0, Math.floor(((index + 1) * matches.length) / (imageUrls.length + 1))),
    );
    const match = matches[ordinal];
    return { position: (match.index ?? 0) + match[0].length, html: imageBlocks[index] };
  });
  let result = contentHtml;
  let offset = 0;
  for (const insertion of insertions) {
    const position = insertion.position + offset;
    result = `${result.slice(0, position)}${insertion.html}${result.slice(position)}`;
    offset += insertion.html.length;
  }
  return result;
}

async function uploadCover(page: Page, cover: PublicationAsset) {
  const { bytes, mime } = await downloadAsset(cover);
  const dir = await mkdtemp(path.join(os.tmpdir(), "xianwen-toutiao-cover-"));
  const extension = mime.includes("png") ? ".png" : mime.includes("webp") ? ".webp" : ".jpg";
  const filename = path.join(dir, `cover${extension}`);
  await writeFile(filename, bytes);
  try {
    const labels = page.locator(".article-cover-radio-group label, .article-cover-radio-group .byte-radio");
    for (let index = 0; index < (await labels.count().catch(() => 0)); index += 1) {
      const label = labels.nth(index);
      const value = (await label.textContent().catch(() => "")) || "";
      if (value.includes("单图")) {
        await label.click().catch(() => undefined);
        await page.waitForTimeout(500);
        break;
      }
    }
    const add = page.locator(".article-cover-add").first();
    if (await add.isVisible({ timeout: 1200 }).catch(() => false)) {
      await add.scrollIntoViewIfNeeded().catch(() => undefined);
      await add.click().catch(() => undefined);
      await page.waitForTimeout(500);
    }
    const file = page.locator('input[type="file"]').last();
    if ((await file.count().catch(() => 0)) === 0) return false;
    await file.setInputFiles(filename);
    await page.waitForTimeout(1800);
    const confirm = page.locator('button:has-text("确定"), button:has-text("确认")').last();
    if (await confirm.isVisible({ timeout: 1200 }).catch(() => false)) {
      if (!(await confirm.isDisabled().catch(() => true))) await confirm.click().catch(() => undefined);
    }
    return true;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function normalizedText(value: string) {
  return value.replace(/<[^>]+>/g, " ").replace(/&nbsp;/gi, " ").replace(/\s+/g, "").trim();
}

export function isSafeToutiaoManagementUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.hostname === "mp.toutiao.com"
      && url.pathname.startsWith("/profile_v4/");
  } catch {
    return false;
  }
}

export function toutiaoPublicArticleId(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !["toutiao.com", "www.toutiao.com"].includes(url.hostname)) return "";
    return url.pathname.match(/^\/(?:article|group)\/(\d+)\/?$/)?.[1]
      || url.pathname.match(/^\/[ia](\d+)\/?$/)?.[1]
      || "";
  } catch {
    return "";
  }
}

export function isBoundToutiaoPublicUrl(
  value: string,
  expectedExternalId: string | undefined,
  expectedTitle: string | undefined,
  contextText: string,
) {
  const articleId = toutiaoPublicArticleId(value);
  if (!articleId) return false;
  if (expectedExternalId && articleId !== expectedExternalId) return false;
  if (expectedTitle && !normalizedText(contextText).includes(normalizedText(expectedTitle))) return false;
  return Boolean(expectedExternalId || expectedTitle);
}

function toutiaoManagementArticleId(value: string) {
  if (!isSafeToutiaoManagementUrl(value)) return "";
  const url = new URL(value);
  return url.searchParams.get("id")
    || url.searchParams.get("group_id")
    || url.searchParams.get("article_id")
    || url.pathname.match(/\/(\d{6,})(?:\/|$)/)?.[1]
    || "";
}

function isToutiaoAuthOrRiskPage(url: string, body = "") {
  const marker = `${url} ${body}`.toLowerCase();
  return ["login", "passport", "captcha", "verify", "challenge", "安全验证", "访问异常", "请完成验证"].some(
    (value) => marker.includes(value),
  );
}

async function editorMatches(page: Page, expectedTitle: string, expectedContent: string) {
  const title = page.locator('textarea[placeholder*="标题"], textarea').first();
  const editor = page.locator('div[contenteditable="true"]').first();
  if (!(await title.isVisible({ timeout: 3_000 }).catch(() => false))) return false;
  if (!(await editor.isVisible({ timeout: 3_000 }).catch(() => false))) return false;
  const actualTitle = await title.inputValue().catch(() => "");
  const actualContent = await editor.innerText().catch(() => "");
  const expectedSnippet = normalizedText(expectedContent).slice(0, 48);
  return normalizedText(actualTitle) === normalizedText(expectedTitle.slice(0, 30))
    && Boolean(expectedSnippet)
    && normalizedText(actualContent).includes(expectedSnippet);
}

async function saveDraft(page: Page) {
  const beforeUrl = page.url();
  const control = page.locator(
    'button:has-text("保存草稿"), button:has-text("存草稿"), [role="button"]:has-text("保存草稿")',
  ).first();
  if (!(await control.isVisible({ timeout: 3_000 }).catch(() => false))) return false;
  if (await control.isDisabled().catch(() => true)) return false;
  await control.click();
  await page.waitForTimeout(1_200);
  const text = (await page.locator("body").innerText().catch(() => "")).slice(-20_000);
  const explicitSuccess = ["保存成功", "已保存", "草稿已保存"].some((value) => text.includes(value));
  const changedToDraft = page.url() !== beforeUrl
    && isSafeToutiaoManagementUrl(page.url())
    && Boolean(toutiaoManagementArticleId(page.url()));
  return explicitSuccess || changedToDraft;
}

async function saveAndReloadDraft(page: Page, expectedTitle: string, expectedContent: string) {
  if (!(await saveDraft(page))) return false;
  const savedUrl = page.url();
  if (!isSafeToutiaoManagementUrl(savedUrl) || !toutiaoManagementArticleId(savedUrl)) return false;
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForTimeout(1_200);
  const body = (await page.locator("body").innerText().catch(() => "")).slice(0, 80_000);
  if (isToutiaoAuthOrRiskPage(page.url(), body) || !isSafeToutiaoManagementUrl(page.url())) return false;
  return editorMatches(page, expectedTitle, expectedContent);
}

async function boundPublicLink(
  page: Page,
  expectedExternalId: string | undefined,
  expectedTitle: string | undefined,
) {
  const links = page.locator('a[href*="toutiao.com/article"], a[href*="toutiao.com/group"], a[href*="toutiao.com/i"]');
  const count = Math.min(await links.count().catch(() => 0), 30);
  for (let index = 0; index < count; index += 1) {
    const link = links.nth(index);
    const href = await link.getAttribute("href").catch(() => null);
    if (!href) continue;
    const resolved = (() => {
      try { return new URL(href, page.url()).toString(); } catch { return ""; }
    })();
    const contextText = await link.evaluate((element) => element.closest("article,li,tr,[class*='item'],[class*='card']")?.textContent || element.textContent || "").catch(() => "");
    if (isBoundToutiaoPublicUrl(resolved, expectedExternalId, expectedTitle, contextText)) return resolved;
  }
  return "";
}

async function confirmPublicSubmission(page: Page) {
  const dialog = page.locator('[role="dialog"], .byte-modal, .semi-modal').filter({ hasText: /发布|确认/ }).last();
  if (!(await dialog.isVisible({ timeout: 2_000 }).catch(() => false))) return;
  const confirm = dialog.locator('button:has-text("确认发布"), button:has-text("确认"), button:has-text("发布")').last();
  if (await confirm.isVisible({ timeout: 1_000 }).catch(() => false)) {
    if (!(await confirm.isDisabled().catch(() => true))) await confirm.click();
  }
}

export class ToutiaoPublisher implements PlatformPublisher {
  readonly platformKey = "toutiao";
  // Candidate implementation only; public publishing and image behavior must pass
  // real-account acceptance before this list is expanded.
  readonly verifiedCapabilities = ["auth"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    if (!credentials.cookies?.length && !credentials.origins?.length) return { ok: false };
    const { browser, context } = await createPublisherBrowserContext(credentials);
    try {
      const page = await context.newPage();
      await page.goto(editorUrl, { waitUntil: "domcontentloaded", timeout: 45_000 });
      await page.waitForTimeout(1_200);
      const pageText = (await page.locator("body").innerText().catch(() => "")).slice(0, 50_000);
      if (isToutiaoAuthOrRiskPage(page.url(), pageText) || !isSafeToutiaoManagementUrl(page.url())) return { ok: false };
      const editorReady = await page.locator('textarea[placeholder*="标题"], div[contenteditable="true"]').first()
        .isVisible({ timeout: 5_000 }).catch(() => false);
      return { ok: editorReady };
    } catch {
      return { ok: false };
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    if (!experimental()) return { platformKey: this.platformKey, status: "unknown" };
    if (!input.credentials.cookies?.length && !input.credentials.origins?.length) {
      return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    if (!input.managementUrl || !isSafeToutiaoManagementUrl(input.managementUrl)) {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };
    }
    const { browser, context } = await createPublisherBrowserContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto(input.managementUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1200);
      const body = (await page.locator("body").innerText().catch(() => "")).slice(-40_000);
      if (isToutiaoAuthOrRiskPage(page.url(), body)) {
        return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      if (!isSafeToutiaoManagementUrl(page.url())) {
        return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };
      }
      const managementId = toutiaoManagementArticleId(page.url()) || toutiaoManagementArticleId(input.managementUrl);
      if (input.externalPostId && managementId && input.externalPostId !== managementId) {
        return { platformKey: this.platformKey, status: "unknown", managementUrl: page.url(), safeErrorCode: "publish_result_unconfirmed" };
      }
      const titleBound = Boolean(input.expectedTitle?.trim())
        && normalizedText(body).includes(normalizedText(input.expectedTitle || ""));
      if (["审核不通过", "发布失败", "已驳回", "未通过"].some((value) => body.includes(value))) {
        return titleBound || Boolean(input.externalPostId && managementId === input.externalPostId)
          ? { platformKey: this.platformKey, status: "failed", managementUrl: page.url(), safeErrorCode: "content_rejected" }
          : { platformKey: this.platformKey, status: "unknown", managementUrl: page.url() };
      }
      const href = await boundPublicLink(page, input.externalPostId || managementId || undefined, input.expectedTitle);
      if (href) {
        return { platformKey: this.platformKey, status: "published", publicUrl: href, managementUrl: page.url() };
      }
      if (
        ["审核中", "待审核", "处理中", "已发布"].some((value) => body.includes(value))
        && (titleBound || Boolean(input.externalPostId && managementId === input.externalPostId))
      ) {
        return { platformKey: this.platformKey, status: "submitted", managementUrl: page.url() };
      }
      return { platformKey: this.platformKey, status: "unknown", managementUrl: page.url() };
    } catch {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "platform_unavailable" };
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    if (!experimental()) {
      return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: "platform_not_verified" };
    }
    if (!input.credentials.cookies?.length && !input.credentials.origins?.length) {
      return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }

    const { browser, context } = await createPublisherBrowserContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto(editorUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1800);
      const initialBody = (await page.locator("body").innerText().catch(() => "")).slice(0, 50_000);
      if (isToutiaoAuthOrRiskPage(page.url(), initialBody) || !isSafeToutiaoManagementUrl(page.url())) {
        return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }

      const title = page.locator('textarea[placeholder*="标题"], textarea').first();
      const editor = page.locator('div[contenteditable="true"]').first();
      if (!(await title.isVisible({ timeout: 3000 }).catch(() => false)) || !(await editor.isVisible({ timeout: 3000 }).catch(() => false))) {
        return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "editor_changed" };
      }
      await title.fill(input.title.slice(0, 30));

      const inlineUrls: string[] = [];
      for (const asset of input.assets.filter((item) => item.role !== "cover").slice(0, 6)) {
        try {
          const url = await uploadInlineImage(page, asset);
          if (url) inlineUrls.push(url);
        } catch {
          // A single optional illustration must not prevent the article from publishing.
        }
      }
      const finalHtml = injectImages(input.contentHtml, inlineUrls);
      await editor.click();
      await page.evaluate((html) => {
        const element = document.querySelector('div[contenteditable="true"]') as HTMLDivElement | null;
        if (!element) return;
        element.innerHTML = html;
        element.dispatchEvent(new InputEvent("input", { bubbles: true, inputType: "insertText" }));
      }, finalHtml);
      await page.waitForTimeout(800);
      if (!(await editorMatches(page, input.title, input.contentText))) {
        return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "editor_changed" };
      }

      const cover = input.assets.find((item) => item.role === "cover");
      if (cover) await uploadCover(page, cover).catch(() => false);

      if (!(await saveAndReloadDraft(page, input.title, input.contentText))) {
        return {
          success: false,
          platformKey: this.platformKey,
          status: "action_required",
          managementUrl: page.url(),
          safeErrorCode: "draft_save_unconfirmed",
        };
      }
      const savedDraftId = toutiaoManagementArticleId(page.url()) || undefined;
      if (input.publishMode === "draft") {
        const externalPostId = savedDraftId;
        return { success: true, platformKey: this.platformKey, status: "drafted", externalPostId, editUrl: page.url(), managementUrl: page.url() };
      }

      const publish = page.locator('button:has-text("预览并发布"), button:has-text("发布")').last();
      if (!(await publish.isVisible({ timeout: 3000 }).catch(() => false))) {
        return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_control_changed" };
      }
      await publish.click();
      await confirmPublicSubmission(page);
      await page.waitForTimeout(8000);
      const body = (await page.locator("body").innerText().catch(() => "")).slice(-40_000);
      if (isToutiaoAuthOrRiskPage(page.url(), body)) {
        return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: "publish_result_unconfirmed" };
      }
      if (["发布失败", "提交失败", "不符合", "审核不通过"].some((value) => body.includes(value))) {
        return { success: false, platformKey: this.platformKey, status: "failed", managementUrl: page.url(), safeErrorCode: "content_rejected" };
      }
      const managementId = toutiaoManagementArticleId(page.url()) || savedDraftId;
      const href = await boundPublicLink(page, managementId, input.title);
      if (href) {
        return { success: true, platformKey: this.platformKey, status: "published", externalPostId: toutiaoPublicArticleId(href), publicUrl: href, managementUrl: isSafeToutiaoManagementUrl(page.url()) ? page.url() : undefined };
      }
      if (
        ["发布成功", "提交成功", "审核中", "待审核", "处理中"].some((value) => body.includes(value))
        && normalizedText(body).includes(normalizedText(input.title))
        && isSafeToutiaoManagementUrl(page.url())
      ) {
        return { success: true, platformKey: this.platformKey, status: "submitted", externalPostId: managementId, managementUrl: page.url() };
      }
      return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_result_unconfirmed" };
    } catch (error) {
      const code = error instanceof Error ? error.message : "platform_unavailable";
      return {
        success: false,
        platformKey: this.platformKey,
        status: code === "media_invalid" ? "failed" : "action_required",
        safeErrorCode: code === "media_invalid" ? "media_invalid" : "platform_unavailable",
      };
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }
}
