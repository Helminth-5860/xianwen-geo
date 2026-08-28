import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import { chromium, type BrowserContext, type Page } from "playwright";

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
const headless = (process.env.PUBLISHING_WORKER_BROWSER_HEADLESS || "true").toLowerCase() !== "false";
const editorUrl = "https://mp.toutiao.com/profile_v4/graphic/publish";

function storedCookies(credentials: PlatformCredentials) {
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

function safeToutiaoUrl(value: string) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && (url.hostname === "mp.toutiao.com" || url.hostname.endsWith(".toutiao.com"));
  } catch {
    return false;
  }
}

async function newContext(credentials: PlatformCredentials) {
  const browser = await chromium.launch({ headless, args: ["--disable-dev-shm-usage", "--no-sandbox"] });
  const context = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: "zh-CN" });
  const values = storedCookies(credentials);
  if (values.length) await context.addCookies(values);
  return { browser, context };
}

export class ToutiaoPublisher implements PlatformPublisher {
  readonly platformKey = "toutiao";
  // Candidate implementation only; public publishing and image behavior must pass
  // real-account acceptance before this list is expanded.
  readonly verifiedCapabilities = ["auth"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    return {
      ok: Boolean(credentials.cookies?.some((item) => ["sessionid", "sid_tt"].includes(item.name) && item.value)),
    };
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    if (!experimental()) return { platformKey: this.platformKey, status: "unknown" };
    if (!input.credentials.cookies?.length) {
      return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    if (!input.managementUrl || !safeToutiaoUrl(input.managementUrl)) {
      return { platformKey: this.platformKey, status: "unknown" };
    }
    const { browser, context } = await newContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto(input.managementUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1200);
      if (page.url().toLowerCase().includes("login")) {
        return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      const body = (await page.locator("body").innerText().catch(() => "")).slice(-40_000);
      if (["审核不通过", "发布失败", "已驳回", "未通过"].some((value) => body.includes(value))) {
        return { platformKey: this.platformKey, status: "failed", managementUrl: page.url(), safeErrorCode: "content_rejected" };
      }
      const publicLink = page.locator('a[href*="toutiao.com/article"], a[href*="www.toutiao.com/article"]').first();
      const href = await publicLink.getAttribute("href").catch(() => null);
      if (href && /^https:\/\//.test(href)) {
        return { platformKey: this.platformKey, status: "published", publicUrl: href, managementUrl: page.url() };
      }
      if (["审核中", "待审核", "处理中", "已发布"].some((value) => body.includes(value))) {
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
    if (!input.credentials.cookies?.length) {
      return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }

    const { browser, context } = await newContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto(editorUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1800);
      if (page.url().toLowerCase().includes("login")) {
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

      const cover = input.assets.find((item) => item.role === "cover");
      if (cover) await uploadCover(page, cover).catch(() => false);

      if (input.publishMode === "draft") {
        return { success: true, platformKey: this.platformKey, status: "drafted", editUrl: page.url(), managementUrl: page.url() };
      }

      const publish = page.locator('button:has-text("预览并发布"), button:has-text("发布")').last();
      if (!(await publish.isVisible({ timeout: 3000 }).catch(() => false))) {
        return { success: false, platformKey: this.platformKey, status: "action_required", managementUrl: page.url(), safeErrorCode: "publish_control_changed" };
      }
      await publish.click();
      await page.waitForTimeout(8000);
      const body = (await page.locator("body").innerText().catch(() => "")).slice(-40_000);
      if (["发布失败", "提交失败", "不符合", "审核不通过"].some((value) => body.includes(value))) {
        return { success: false, platformKey: this.platformKey, status: "failed", managementUrl: page.url(), safeErrorCode: "content_rejected" };
      }
      const publicLink = page.locator('a[href*="toutiao.com/article"], a[href*="www.toutiao.com/article"]').first();
      const href = await publicLink.getAttribute("href").catch(() => null);
      if (href && /^https:\/\//.test(href)) {
        return { success: true, platformKey: this.platformKey, status: "published", publicUrl: href, managementUrl: page.url() };
      }
      if (["发布成功", "提交成功", "审核中", "待审核", "处理中"].some((value) => body.includes(value))) {
        return { success: true, platformKey: this.platformKey, status: "submitted", managementUrl: page.url() };
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
