import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { chromium, type BrowserContext } from "playwright";

import type { PlatformCredentials, PlatformPublisher, PublicationInput, PublicationResult } from "./types.js";

const experimental = () => new Set(
  (process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS || "").split(",").map((item) => item.trim().toLowerCase()).filter(Boolean),
).has("baijiahao");
const headless = (process.env.PUBLISHING_WORKER_BROWSER_HEADLESS || "true").toLowerCase() !== "false";

function cookiePayload(credentials: PlatformCredentials) {
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
    return { ok: Boolean(credentials.cookies?.some((item) => item.name === "BDUSS" && item.value)) };
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    if (!experimental()) return { success: false, platformKey: this.platformKey, status: "action_required", safeErrorCode: "platform_not_verified" };
    if (!input.credentials.cookies?.length) return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    const browser = await chromium.launch({ headless, args: ["--disable-dev-shm-usage", "--no-sandbox"] });
    let context: BrowserContext | null = null;
    let coverDir = "";
    try {
      context = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: "zh-CN" });
      const cookies = cookiePayload(input.credentials);
      if (cookies.length) await context.addCookies(cookies);
      const page = await context.newPage();
      await page.goto("https://baijiahao.baidu.com/builder/rc/edit?type=news&is_from_cms=1", { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1800);
      if (page.url().includes("passport.baidu.com") || page.url().toLowerCase().includes("login")) {
        return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      const editors = page.locator("[data-lexical-editor='true']");
      if (!(await editors.count())) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "editor_changed" };
      await editors.first().fill(input.title.slice(0, 64));
      const body = page.frameLocator("#ueditor_0").locator("body");
      await body.waitFor({ state: "visible", timeout: 15_000 });
      await body.fill(input.contentText);

      const cover = input.assets.find((item) => item.role === "cover") || input.assets[0];
      if (cover) {
        const trigger = page.getByText("选择封面", { exact: false }).first();
        if (await trigger.isVisible({ timeout: 1200 }).catch(() => false)) {
          await trigger.click();
          const fileInput = page.locator(".cheetah-upload input[type='file']").first();
          if (await fileInput.isVisible({ timeout: 3000 }).catch(() => false)) {
            const local = await downloadCover(cover.url);
            coverDir = local.dir;
            await fileInput.setInputFiles(local.filename);
            const confirm = page.locator(".cheetah-btn-primary").filter({ hasText: "确定" }).first();
            if (await confirm.isVisible({ timeout: 10_000 }).catch(() => false)) await confirm.click();
          }
        }
      }

      if (input.publishMode === "draft") return { success: true, platformKey: this.platformKey, status: "drafted", editUrl: page.url(), managementUrl: page.url() };
      const publish = page.locator("[data-testid='publish-btn'], button:has-text('发布')").first();
      if (!(await publish.isVisible({ timeout: 3000 }).catch(() => false))) return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_control_changed" };
      await publish.click();
      await page.waitForTimeout(2500);
      const text = await page.locator("body").innerText().catch(() => "");
      if (["发布成功", "提交成功", "审核中", "待审核"].some((item) => text.includes(item))) {
        return { success: true, platformKey: this.platformKey, status: "submitted", managementUrl: page.url() };
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
