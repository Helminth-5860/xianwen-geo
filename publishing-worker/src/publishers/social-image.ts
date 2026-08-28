import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { chromium, type BrowserContext } from "playwright";

import type { PlatformCredentials, PlatformPublisher, PublicationAsset, PublicationInput, PublicationResult } from "./types.js";

const experimentalKeys = new Set(
  (process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS || "")
    .split(",")
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean),
);
const headless = (process.env.PUBLISHING_WORKER_BROWSER_HEADLESS || "true").toLowerCase() !== "false";

function storedCookies(credentials: PlatformCredentials) {
  return (credentials.cookies || []).filter((item) => item.name && item.domain).map((item) => ({
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

async function localAssets(assets: PublicationAsset[]) {
  const selected = assets.slice(0, 9);
  const dir = await mkdtemp(path.join(os.tmpdir(), "xianwen-social-"));
  const files: string[] = [];
  try {
    for (let index = 0; index < selected.length; index += 1) {
      const response = await fetch(selected[index].url, { redirect: "follow" });
      if (!response.ok) throw new Error("media_download_failed");
      const bytes = Buffer.from(await response.arrayBuffer());
      if (!bytes.length || bytes.length > 15 * 1024 * 1024) throw new Error("media_invalid");
      const type = response.headers.get("content-type") || "image/jpeg";
      const ext = type.includes("png") ? ".png" : type.includes("webp") ? ".webp" : ".jpg";
      const filename = path.join(dir, `image-${index}${ext}`);
      await writeFile(filename, bytes);
      files.push(filename);
    }
    return { dir, files };
  } catch (error) {
    await rm(dir, { recursive: true, force: true });
    throw error;
  }
}

async function newContext(credentials: PlatformCredentials) {
  const browser = await chromium.launch({ headless, args: ["--disable-dev-shm-usage", "--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: "zh-CN" });
  const values = storedCookies(credentials);
  if (values.length) await context.addCookies(values);
  return { browser, context };
}

export class XiaohongshuPublisher implements PlatformPublisher {
  readonly platformKey = "xiaohongshu";
  readonly verifiedCapabilities = ["auth"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    return { ok: Boolean(credentials.cookies?.some((item) => ["web_session", "galaxy_creator_session_id"].includes(item.name))) };
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    if (!experimentalKeys.has(this.platformKey)) return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: "platform_not_verified" };
    if (!input.assets.length) return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "media_invalid" };
    const { dir, files } = await localAssets(input.assets);
    const { browser, context } = await newContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto("https://creator.xiaohongshu.com/publish/publish?source=official", { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1600);
      if (page.url().toLowerCase().includes("login")) return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      const tab = page.locator(".creator-tab").filter({ hasText: "上传图文" }).first();
      if (await tab.isVisible({ timeout: 1000 }).catch(() => false)) await tab.click();
      const upload = page.locator('input[type="file"]').first();
      await upload.waitFor({ state: "attached", timeout: 12_000 });
      await upload.setInputFiles(files);
      const title = page.locator('input[placeholder*="填写标题"], input[placeholder*="标题"]').first();
      await title.waitFor({ state: "visible", timeout: 20_000 });
      await title.fill(input.title.slice(0, 20));
      const body = page.locator('[contenteditable="true"], textarea').first();
      await body.fill(input.contentText.slice(0, 1000));
      if (input.tags.length) await body.fill(`${input.contentText.slice(0, 850)}\n${input.tags.slice(0, 8).map((tag) => `#${tag}`).join(" ")}`);
      if (input.publishMode === "draft") return { success: true, platformKey: this.platformKey, status: "drafted", editUrl: page.url(), managementUrl: page.url() };
      const button = page.locator("button.ce-btn.bg-red, button:has-text('发布')").first();
      if (!(await button.isVisible({ timeout: 3000 }).catch(() => false))) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_control_changed" };
      await button.click();
      const success = await page.getByText("发布成功", { exact: false }).first().isVisible({ timeout: 60_000 }).catch(() => false);
      if (!success) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_result_unconfirmed" };
      return { success: true, platformKey: this.platformKey, status: "submitted", managementUrl: page.url() };
    } catch (error) {
      const code = error instanceof Error ? error.message : "platform_unavailable";
      return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: code === "media_invalid" ? "media_invalid" : "platform_unavailable" };
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
      await rm(dir, { recursive: true, force: true });
    }
  }
}

export class DouyinImagePublisher implements PlatformPublisher {
  readonly platformKey = "douyin";
  readonly verifiedCapabilities = ["auth"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    return { ok: Boolean(credentials.cookies?.some((item) => ["sessionid", "sid_tt"].includes(item.name))) };
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    if (!experimentalKeys.has(this.platformKey)) return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: "platform_not_verified" };
    if (!input.assets.length) return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "media_invalid" };
    const { dir, files } = await localAssets(input.assets.slice(0, 1));
    const { browser, context } = await newContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto("https://creator.douyin.com/creator-micro/content/upload", { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1800);
      if (page.url().toLowerCase().includes("login")) return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      const tabs = page.locator("[class*='tab-item']");
      if ((await tabs.count()) > 1) await tabs.nth(1).click();
      const uploads = page.locator('input[type="file"]');
      const count = await uploads.count();
      if (!count) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "editor_changed" };
      await uploads.nth(Math.min(1, count - 1)).setInputFiles(files[0]);
      const discard = page.getByText("放弃", { exact: false }).first();
      if (await discard.isVisible({ timeout: 1500 }).catch(() => false)) await discard.click();
      await page.waitForURL("**/post/image**", { timeout: 30_000 }).catch(() => undefined);
      const title = page.locator("input[placeholder='添加作品标题'], input[placeholder*='标题']").first();
      await title.waitFor({ state: "visible", timeout: 15_000 });
      await title.fill(input.title.slice(0, 30));
      const body = page.locator(".zone-container.editor-kit-container, [contenteditable='true'], textarea").first();
      await body.fill(input.contentText.slice(0, 800));
      if (input.publishMode === "draft") return { success: true, platformKey: this.platformKey, status: "drafted", editUrl: page.url(), managementUrl: page.url() };
      const button = page.locator("button:has-text('发布')").first();
      if (!(await button.isVisible({ timeout: 3000 }).catch(() => false))) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_control_changed" };
      await button.click();
      await page.waitForTimeout(2500);
      const bodyText = await page.locator("body").innerText().catch(() => "");
      if (["发布成功", "提交成功", "审核中", "已发布"].some((text) => bodyText.includes(text))) {
        return { success: true, platformKey: this.platformKey, status: "submitted", managementUrl: page.url() };
      }
      return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_result_unconfirmed" };
    } catch (error) {
      const code = error instanceof Error ? error.message : "platform_unavailable";
      return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: code === "media_invalid" ? "media_invalid" : "platform_unavailable" };
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
      await rm(dir, { recursive: true, force: true });
    }
  }
}
