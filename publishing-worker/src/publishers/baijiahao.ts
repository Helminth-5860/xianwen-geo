import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import type { BrowserContext, Page } from "playwright";

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
).has("baijiahao");
const editorUrl = "https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1";

function normalizedText(value: string) {
  return value.replace(/<[^>]+>/g, " ").replace(/&nbsp;/gi, " ").replace(/\s+/g, "").trim();
}

export function isSafeBaijiaManagementUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.hostname === "baijiahao.baidu.com"
      && url.pathname.startsWith("/builder/rc/");
  } catch {
    return false;
  }
}

export function baijiaPublicArticleId(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:") return "";
    if (url.hostname === "baijiahao.baidu.com" && url.pathname === "/s") {
      return url.searchParams.get("id") || "";
    }
    if (url.hostname === "mbd.baidu.com" && url.pathname === "/newspage/data/landingshare") {
      return url.searchParams.get("id") || "";
    }
    return "";
  } catch {
    return "";
  }
}

export function isBoundBaijiaPublicUrl(
  value: string,
  expectedExternalId: string | undefined,
  expectedTitle: string | undefined,
  contextText: string,
) {
  const articleId = baijiaPublicArticleId(value);
  const safeShareUrl = (() => {
    try {
      const url = new URL(value);
      return url.protocol === "https:"
        && url.hostname === "mbd.baidu.com"
        && url.pathname === "/newspage/data/landingshare";
    } catch {
      return false;
    }
  })();
  if (!articleId && !safeShareUrl) return false;
  if (expectedExternalId && articleId !== expectedExternalId) return false;
  if (expectedTitle && !normalizedText(contextText).includes(normalizedText(expectedTitle))) return false;
  return Boolean(expectedExternalId || expectedTitle);
}

function baijiaManagementArticleId(value: string) {
  if (!isSafeBaijiaManagementUrl(value)) return "";
  const url = new URL(value);
  return url.searchParams.get("id")
    || url.searchParams.get("article_id")
    || url.pathname.match(/\/(\d{6,})(?:\/|$)/)?.[1]
    || "";
}

function isBaijiaAuthOrRiskPage(url: string, body = "") {
  const marker = `${url} ${body}`.toLowerCase();
  return ["passport.baidu.com", "login", "captcha", "verify", "challenge", "安全验证", "访问异常", "请完成验证"].some(
    (value) => marker.includes(value),
  );
}

async function editorMatches(page: Page, expectedTitle: string, expectedContent: string) {
  const title = page.locator("[data-lexical-editor='true']").first();
  const body = page.frameLocator("#ueditor_0").locator("body");
  if (!(await title.isVisible({ timeout: 3_000 }).catch(() => false))) return false;
  if (!(await body.isVisible({ timeout: 3_000 }).catch(() => false))) return false;
  const actualTitle = await title.innerText().catch(() => "");
  const actualContent = await body.innerText().catch(() => "");
  const expectedSnippet = normalizedText(expectedContent).slice(0, 48);
  return normalizedText(actualTitle) === normalizedText(expectedTitle.slice(0, 64))
    && Boolean(expectedSnippet)
    && normalizedText(actualContent).includes(expectedSnippet);
}

async function saveDraft(page: Page) {
  const beforeUrl = page.url();
  const button = page.locator(
    'button:has-text("保存草稿"), button:has-text("存草稿"), [role="button"]:has-text("保存草稿")',
  ).first();
  if (!(await button.isVisible({ timeout: 3_000 }).catch(() => false))) return false;
  if (await button.isDisabled().catch(() => true)) return false;
  await button.click();
  await page.waitForTimeout(1_200);
  const text = (await page.locator("body").innerText().catch(() => "")).slice(-20_000);
  const explicitSuccess = ["保存成功", "已保存", "草稿已保存"].some((value) => text.includes(value));
  const changedToDraft = page.url() !== beforeUrl
    && isSafeBaijiaManagementUrl(page.url())
    && Boolean(baijiaManagementArticleId(page.url()));
  return explicitSuccess || changedToDraft;
}

async function saveAndReloadDraft(page: Page, expectedTitle: string, expectedContent: string) {
  if (!(await saveDraft(page))) return false;
  const savedUrl = page.url();
  if (!isSafeBaijiaManagementUrl(savedUrl) || !baijiaManagementArticleId(savedUrl)) return false;
  await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 });
  await page.waitForTimeout(1_200);
  const pageText = (await page.locator("body").innerText().catch(() => "")).slice(0, 80_000);
  if (isBaijiaAuthOrRiskPage(page.url(), pageText) || !isSafeBaijiaManagementUrl(page.url())) return false;
  return editorMatches(page, expectedTitle, expectedContent);
}

async function boundPublicLink(
  page: Page,
  expectedExternalId: string | undefined,
  expectedTitle: string | undefined,
) {
  const links = page.locator('a[href*="baijiahao.baidu.com/s"], a[href*="mbd.baidu.com/newspage/data/landingshare"]');
  const count = Math.min(await links.count().catch(() => 0), 30);
  for (let index = 0; index < count; index += 1) {
    const link = links.nth(index);
    const href = await link.getAttribute("href").catch(() => null);
    if (!href) continue;
    const resolved = (() => {
      try { return new URL(href, page.url()).toString(); } catch { return ""; }
    })();
    const contextText = await link.evaluate((element) => element.closest("article,li,tr,[class*='item'],[class*='card']")?.textContent || element.textContent || "").catch(() => "");
    if (isBoundBaijiaPublicUrl(resolved, expectedExternalId, expectedTitle, contextText)) return resolved;
  }
  return "";
}

async function confirmPublicSubmission(page: Page) {
  const dialog = page.locator('[role="dialog"], .cheetah-modal, .ant-modal').filter({ hasText: /发布|确认/ }).last();
  if (!(await dialog.isVisible({ timeout: 2_000 }).catch(() => false))) return;
  const confirm = dialog.locator('button:has-text("确认发布"), button:has-text("确认"), button:has-text("发布")').last();
  if (await confirm.isVisible({ timeout: 1_000 }).catch(() => false)) {
    if (!(await confirm.isDisabled().catch(() => true))) await confirm.click();
  }
}

async function downloadCover(url: string) {
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error("media_download_failed");
  const bytes = Buffer.from(await response.arrayBuffer());
  if (!bytes.length || bytes.length > 15 * 1024 * 1024) throw new Error("media_invalid");
  const dir = await mkdtemp(path.join(os.tmpdir(), "xianwen-baijia-"));
  const type = response.headers.get("content-type") || "image/jpeg";
  const extension = type.includes("png") ? ".png" : type.includes("webp") ? ".webp" : ".jpg";
  const filename = path.join(dir, `cover${extension}`);
  await writeFile(filename, bytes);
  return { dir, filename };
}

export class BaijiahaoPublisher implements PlatformPublisher {
  readonly platformKey = "baijiahao";
  readonly verifiedCapabilities = ["auth"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    if (!credentials.cookies?.length && !credentials.origins?.length) return { ok: false };
    const { browser, context } = await createPublisherBrowserContext(credentials);
    try {
      const page = await context.newPage();
      await page.goto(editorUrl, { waitUntil: "domcontentloaded", timeout: 45_000 });
      await page.waitForTimeout(1_200);
      const pageText = (await page.locator("body").innerText().catch(() => "")).slice(0, 50_000);
      if (isBaijiaAuthOrRiskPage(page.url(), pageText) || !isSafeBaijiaManagementUrl(page.url())) return { ok: false };
      const editorReady = await page.locator("[data-lexical-editor='true'], #ueditor_0").first()
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
    if (!input.managementUrl || !isSafeBaijiaManagementUrl(input.managementUrl)) {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };
    }
    const { browser, context } = await createPublisherBrowserContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto(input.managementUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1_500);
      const text = (await page.locator("body").innerText().catch(() => "")).slice(-40_000);
      if (isBaijiaAuthOrRiskPage(page.url(), text)) {
        return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      if (!isSafeBaijiaManagementUrl(page.url())) {
        return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };
      }
      const managementId = baijiaManagementArticleId(page.url()) || baijiaManagementArticleId(input.managementUrl);
      if (input.externalPostId && managementId && input.externalPostId !== managementId) {
        return { platformKey: this.platformKey, status: "unknown", managementUrl: page.url(), safeErrorCode: "publish_result_unconfirmed" };
      }
      const titleBound = Boolean(input.expectedTitle?.trim())
        && normalizedText(text).includes(normalizedText(input.expectedTitle || ""));
      if (["审核不通过", "发布失败", "已驳回", "未通过"].some((value) => text.includes(value))) {
        return titleBound || Boolean(input.externalPostId && managementId === input.externalPostId)
          ? { platformKey: this.platformKey, status: "failed", managementUrl: page.url(), safeErrorCode: "content_rejected" }
          : { platformKey: this.platformKey, status: "unknown", managementUrl: page.url() };
      }
      const href = await boundPublicLink(page, input.externalPostId || managementId || undefined, input.expectedTitle);
      if (href) {
        return { platformKey: this.platformKey, status: "published", publicUrl: href, managementUrl: page.url() };
      }
      if (
        ["审核中", "待审核", "处理中", "已发布"].some((value) => text.includes(value))
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
    if (!experimental()) return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: "platform_not_verified" };
    if (!input.credentials.cookies?.length && !input.credentials.origins?.length) return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    const opened = await createPublisherBrowserContext(input.credentials);
    const browser = opened.browser;
    let context: BrowserContext | null = null;
    let coverDir = "";
    try {
      context = opened.context;
      const page = await context.newPage();
      await page.goto(editorUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1800);
      const initialText = (await page.locator("body").innerText().catch(() => "")).slice(0, 50_000);
      if (isBaijiaAuthOrRiskPage(page.url(), initialText) || !isSafeBaijiaManagementUrl(page.url())) {
        return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      const editors = page.locator("[data-lexical-editor='true']");
      if (!(await editors.count())) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "editor_changed" };
      await editors.first().fill(input.title.slice(0, 64));
      const body = page.frameLocator("#ueditor_0").locator("body");
      await body.waitFor({ state: "visible", timeout: 15_000 });
      await body.fill(input.contentText);
      if (!(await editorMatches(page, input.title, input.contentText))) {
        return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "editor_changed" };
      }

      const cover = input.assets.find((item) => item.role === "cover") || input.assets[0];
      if (cover) {
        const trigger = page.getByText("选择封面", { exact: false }).first();
        if (await trigger.isVisible({ timeout: 1200 }).catch(() => false)) {
          await trigger.click();
          const fileInput = page.locator(".cheetah-upload input[type='file']").first();
          if ((await fileInput.count().catch(() => 0)) > 0) {
            const local = await downloadCover(cover.url);
            coverDir = local.dir;
            await fileInput.setInputFiles(local.filename);
            const confirm = page.locator(".cheetah-btn-primary").filter({ hasText: "确定" }).first();
            if (await confirm.isVisible({ timeout: 10_000 }).catch(() => false)) await confirm.click();
          }
        }
      }

      if (!(await saveAndReloadDraft(page, input.title, input.contentText))) {
        return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "draft_save_unconfirmed" };
      }
      const savedDraftId = baijiaManagementArticleId(page.url()) || undefined;
      if (input.publishMode === "draft") {
        const externalPostId = savedDraftId;
        return { success: true, platformKey: this.platformKey, status: "drafted", externalPostId, editUrl: page.url(), managementUrl: page.url() };
      }
      const publish = page.locator("[data-testid='publish-btn'], button:has-text('发布')").first();
      if (!(await publish.isVisible({ timeout: 3000 }).catch(() => false))) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_control_changed" };
      await publish.click();
      await confirmPublicSubmission(page);
      await page.waitForTimeout(2500);
      const text = await page.locator("body").innerText().catch(() => "");
      if (isBaijiaAuthOrRiskPage(page.url(), text)) {
        return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: "publish_result_unconfirmed" };
      }
      const managementId = baijiaManagementArticleId(page.url()) || savedDraftId;
      const href = await boundPublicLink(page, managementId, input.title);
      if (href) {
        return { success: true, platformKey: this.platformKey, status: "published", externalPostId: baijiaPublicArticleId(href) || managementId, publicUrl: href, managementUrl: isSafeBaijiaManagementUrl(page.url()) ? page.url() : undefined };
      }
      if (
        ["发布成功", "提交成功", "审核中", "待审核"].some((item) => text.includes(item))
        && normalizedText(text).includes(normalizedText(input.title))
        && isSafeBaijiaManagementUrl(page.url())
      ) {
        return { success: true, platformKey: this.platformKey, status: "submitted", externalPostId: managementId, managementUrl: page.url() };
      }
      if (["发布失败", "不符合", "重复", "错误"].some((item) => text.includes(item))) {
        return { success: false, platformKey: this.platformKey, status: "failed", managementUrl: page.url(), safeErrorCode: "content_rejected" };
      }
      return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_result_unconfirmed" };
    } catch (error) {
      const code = error instanceof Error ? error.message : "platform_unavailable";
      return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: code === "media_invalid" ? "media_invalid" : "platform_unavailable" };
    } finally {
      if (coverDir) await rm(coverDir, { recursive: true, force: true });
      if (context) await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }
}
