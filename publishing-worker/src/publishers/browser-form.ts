import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { chromium, type BrowserContext, type Locator, type Page } from "playwright";

import type {
  PlatformCredentials,
  PlatformPublisher,
  PublicationAsset,
  PublicationInput,
  PublicationResult,
  PublicationStatusInput,
  PublicationStatusResult,
} from "./types.js";

export type BrowserPublisherConfig = Readonly<{
  platformKey: string;
  editorUrl: string;
  loginMarkers?: string[];
  titleSelectors: string[];
  contentSelectors: string[];
  coverTriggerTexts?: string[];
  coverInputSelectors?: string[];
  publishSelectors: string[];
  successTexts: string[];
  reviewTexts?: string[];
  failureTexts?: string[];
  publicLinkSelectors?: string[];
}>;

const experimentalKeys = new Set(
  (process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean),
);

const browserHeadless = (process.env.PUBLISHING_WORKER_BROWSER_HEADLESS || "true").toLowerCase() !== "false";

function cookies(credentials: PlatformCredentials) {
  return (credentials.cookies || [])
    .filter((item) => item.name && item.domain)
    .map((item) => ({
      name: item.name,
      value: item.value,
      domain: item.domain,
      path: item.path || "/",
      ...(typeof item.expires === "number" && item.expires > 0 ? { expires: item.expires } : {}),
      ...(typeof item.httpOnly === "boolean" ? { httpOnly: item.httpOnly } : {}),
      ...(typeof item.secure === "boolean" ? { secure: item.secure } : {}),
      ...(item.sameSite ? { sameSite: item.sameSite } : {}),
    }));
}

async function firstVisible(page: Page, selectors: string[]): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (await locator.isVisible({ timeout: 1200 }).catch(() => false)) return locator;
  }
  return null;
}

async function firstAttached(page: Page, selectors: string[]): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if ((await locator.count().catch(() => 0)) > 0) return locator;
  }
  return null;
}

async function downloadAsset(asset: PublicationAsset) {
  const response = await fetch(asset.url, { redirect: "follow" });
  if (!response.ok) throw new Error("media_download_failed");
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length === 0 || bytes.length > 15 * 1024 * 1024) throw new Error("media_invalid");
  const contentType = response.headers.get("content-type") || "image/jpeg";
  const extension = contentType.includes("png") ? ".png" : contentType.includes("webp") ? ".webp" : ".jpg";
  const dir = await mkdtemp(path.join(os.tmpdir(), "xianwen-publish-"));
  const filename = path.join(dir, `asset${extension}`);
  await writeFile(filename, bytes);
  return { filename, dir };
}

async function uploadCover(page: Page, input: PublicationInput, config: BrowserPublisherConfig) {
  const cover = input.assets.find((item) => item.role === "cover") || input.assets[0];
  if (!cover) return;
  for (const text of config.coverTriggerTexts || []) {
    const trigger = page.getByText(text, { exact: false }).first();
    if (await trigger.isVisible({ timeout: 800 }).catch(() => false)) {
      await trigger.click().catch(() => undefined);
      await page.waitForTimeout(600);
      break;
    }
  }
  const selectorList = config.coverInputSelectors?.length
    ? config.coverInputSelectors
    : ['input[type="file"]'];
  const inputLocator = await firstAttached(page, selectorList);
  if (!inputLocator) return;
  const { filename, dir } = await downloadAsset(cover);
  try {
    await inputLocator.setInputFiles(filename);
    await page.waitForTimeout(1200);
    const confirm = page.getByRole("button", { name: /确定|确认|完成/ }).first();
    if (await confirm.isVisible({ timeout: 800 }).catch(() => false)) {
      await confirm.click().catch(() => undefined);
      await page.waitForTimeout(500);
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

function platformRoot(hostname: string) {
  const parts = hostname.toLowerCase().split(".").filter(Boolean);
  return parts.length >= 2 ? parts.slice(-2).join(".") : hostname.toLowerCase();
}

function statusUrlAllowed(managementUrl: string, editorUrl: string) {
  try {
    const target = new URL(managementUrl);
    const editor = new URL(editorUrl);
    if (target.protocol !== "https:") return false;
    return platformRoot(target.hostname) === platformRoot(editor.hostname);
  } catch {
    return false;
  }
}

async function detectPublicUrl(page: Page, config: BrowserPublisherConfig): Promise<string | undefined> {
  for (const selector of config.publicLinkSelectors || []) {
    const locator = page.locator(selector).first();
    const href = await locator.getAttribute("href").catch(() => null);
    if (href && /^https:\/\//.test(href) && statusUrlAllowed(href, config.editorUrl)) return href;
  }
  const current = page.url();
  if (
    statusUrlAllowed(current, config.editorUrl) &&
    !current.includes("/edit") &&
    !current.includes("/publish") &&
    !current.includes("/write") &&
    !current.includes("builder")
  ) {
    return current;
  }
  return undefined;
}

export class BrowserFormPublisher implements PlatformPublisher {
  readonly platformKey: string;
  readonly verifiedCapabilities = ["auth"] as const;

  constructor(private readonly config: BrowserPublisherConfig) {
    this.platformKey = config.platformKey;
  }

  private enabled() {
    return experimentalKeys.has(this.platformKey);
  }

  async checkAuth(credentials: PlatformCredentials) {
    return { ok: Boolean(credentials.cookies?.length) };
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    if (!this.enabled()) return { platformKey: this.platformKey, status: "unknown" };
    if (!input.credentials.cookies?.length) {
      return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    if (!input.managementUrl || !statusUrlAllowed(input.managementUrl, this.config.editorUrl)) {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };
    }

    const browser = await chromium.launch({
      headless: browserHeadless,
      args: ["--disable-dev-shm-usage", "--no-sandbox"],
    });
    let context: BrowserContext | null = null;
    try {
      context = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: "zh-CN" });
      const stored = cookies(input.credentials);
      if (stored.length) await context.addCookies(stored);
      const page = await context.newPage();
      await page.goto(input.managementUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1200);
      const currentUrl = page.url().toLowerCase();
      if ((this.config.loginMarkers || ["login", "signin", "passport"]).some((marker) => currentUrl.includes(marker))) {
        return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      const body = (await page.locator("body").innerText().catch(() => "")).slice(-40_000);
      const failure = (this.config.failureTexts || ["审核不通过", "发布失败", "已驳回", "未通过"]).some((item) => body.includes(item));
      if (failure) return { platformKey: this.platformKey, status: "failed", managementUrl: page.url(), safeErrorCode: "content_rejected" };
      const publicUrl = await detectPublicUrl(page, this.config);
      if (publicUrl) return { platformKey: this.platformKey, status: "published", publicUrl, managementUrl: page.url() };
      if ([...(this.config.reviewTexts || []), "审核中", "待审核", "处理中"].some((item) => body.includes(item))) {
        return { platformKey: this.platformKey, status: "submitted", managementUrl: page.url() };
      }
      return { platformKey: this.platformKey, status: "unknown", managementUrl: page.url() };
    } catch {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "platform_unavailable" };
    } finally {
      if (context) await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    if (!this.enabled()) {
      return {
        success: false,
        platformKey: this.platformKey,
        status: "action_required",
        safeErrorCode: "platform_not_verified",
      };
    }
    if (!input.credentials.cookies?.length) {
      return {
        success: false,
        platformKey: this.platformKey,
        status: "auth_required",
        safeErrorCode: "authorization_required",
      };
    }

    const browser = await chromium.launch({
      headless: browserHeadless,
      args: ["--disable-dev-shm-usage", "--no-sandbox"],
    });
    let context: BrowserContext | null = null;
    try {
      context = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: "zh-CN" });
      const stored = cookies(input.credentials);
      if (stored.length) await context.addCookies(stored);
      const page = await context.newPage();
      await page.goto(this.config.editorUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1500);
      const currentUrl = page.url().toLowerCase();
      if ((this.config.loginMarkers || ["login", "signin", "passport"]).some((marker) => currentUrl.includes(marker))) {
        return {
          success: false,
          platformKey: this.platformKey,
          status: "auth_required",
          safeErrorCode: "authorization_required",
        };
      }

      const title = await firstVisible(page, this.config.titleSelectors);
      const content = await firstVisible(page, this.config.contentSelectors);
      if (!title || !content) {
        return {
          success: false,
          platformKey: this.platformKey,
          status: "action_required",
          managementUrl: page.url(),
          safeErrorCode: "editor_changed",
        };
      }
      await title.fill(input.title);
      await content.fill(input.contentText || input.contentHtml.replace(/<[^>]+>/g, " "));
      await uploadCover(page, input, this.config).catch(() => undefined);

      if (input.publishMode === "draft") {
        return {
          success: true,
          platformKey: this.platformKey,
          status: "drafted",
          editUrl: page.url(),
          managementUrl: page.url(),
        };
      }

      const publish = await firstVisible(page, this.config.publishSelectors);
      if (!publish) {
        return {
          success: false,
          platformKey: this.platformKey,
          status: "action_required",
          managementUrl: page.url(),
          safeErrorCode: "publish_control_changed",
        };
      }
      await publish.click();
      await page.waitForTimeout(2500);
      const body = (await page.locator("body").innerText().catch(() => "")).slice(-30_000);
      const failure = (this.config.failureTexts || ["发布失败", "提交失败", "不符合", "异常"]).find((item) => body.includes(item));
      if (failure) {
        return {
          success: false,
          platformKey: this.platformKey,
          status: "failed",
          managementUrl: page.url(),
          safeErrorCode: "content_rejected",
        };
      }
      const publicUrl = await detectPublicUrl(page, this.config);
      if (publicUrl) {
        return {
          success: true,
          platformKey: this.platformKey,
          status: "published",
          publicUrl,
          managementUrl: page.url(),
        };
      }
      const submitted = [...(this.config.reviewTexts || []), ...this.config.successTexts].some((item) => body.includes(item));
      if (submitted) {
        return {
          success: true,
          platformKey: this.platformKey,
          status: "submitted",
          managementUrl: page.url(),
        };
      }
      return {
        success: false,
        platformKey: this.platformKey,
        status: "action_required",
        managementUrl: page.url(),
        safeErrorCode: "publish_result_unconfirmed",
      };
    } catch (error) {
      const code = error instanceof Error ? error.message : "platform_unavailable";
      return {
        success: false,
        platformKey: this.platformKey,
        status: code === "media_invalid" ? "failed" : "action_required",
        safeErrorCode: code === "media_invalid" ? "media_invalid" : "platform_unavailable",
      };
    } finally {
      if (context) await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }
}
