import { mkdtemp, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import type { Locator, Page } from "playwright";

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

type SocialPlatformKey = "xiaohongshu" | "douyin";

type SocialPlatformConfig = Readonly<{
  platformKey: SocialPlatformKey;
  editorUrl: string;
  sessionCookieNames: readonly string[];
  sessionOriginHosts: readonly string[];
  titleLimit: number;
  contentLimit: number;
  tagLimit: number;
  imageLimit: number;
  tabSelectors: readonly string[];
  uploadSelectors: readonly string[];
  previewSelectors: readonly string[];
  uploadPendingSelectors: readonly string[];
  titleSelectors: readonly string[];
  contentSelectors: readonly string[];
  draftSelectors: readonly string[];
  publishSelectors: readonly string[];
  publicLinkSelectors: readonly string[];
  loginUrlMarkers: readonly string[];
  draftSuccessTexts: readonly string[];
  submittedTexts: readonly string[];
  failureTexts: readonly string[];
}>;

const MAX_IMAGE_BYTES = 15 * 1024 * 1024;
const MAX_TOTAL_IMAGE_BYTES = 90 * 1024 * 1024;
const DOWNLOAD_TIMEOUT_MS = 30_000;
const UPLOAD_TIMEOUT_MS = 75_000;

const REQUIRED_FIELD_TEXTS = [
  "请输入标题",
  "请填写标题",
  "标题不能为空",
  "请输入正文",
  "请输入描述",
  "请填写描述",
  "正文不能为空",
  "请上传图片",
  "至少上传",
] as const;

const MEDIA_FAILURE_TEXTS = [
  "上传失败",
  "图片上传失败",
  "图片格式不支持",
  "图片过大",
  "图片尺寸不符合",
  "图片违规",
] as const;

const CONFIGS: Readonly<Record<SocialPlatformKey, SocialPlatformConfig>> = {
  xiaohongshu: {
    platformKey: "xiaohongshu",
    editorUrl: "https://creator.xiaohongshu.com/publish/publish?source=official",
    sessionCookieNames: ["web_session", "galaxy_creator_session_id"],
    sessionOriginHosts: ["creator.xiaohongshu.com", "edith.xiaohongshu.com"],
    titleLimit: 20,
    contentLimit: 1_000,
    tagLimit: 8,
    imageLimit: 9,
    tabSelectors: [
      '[role="tab"]:has-text("上传图文")',
      '.creator-tab:has-text("上传图文")',
      '[class*="tab"]:has-text("上传图文")',
    ],
    uploadSelectors: [
      'input[type="file"][multiple]:not([accept*="video"])',
      'input[type="file"][accept*="image"]',
    ],
    previewSelectors: [
      '[class*="image-list"] [class*="image-item"]',
      '[class*="img-list"] [class*="img-item"]',
      '[class*="upload"] [class*="preview"] img',
      '[class*="upload-item"] img',
      'img[src^="blob:"]',
    ],
    uploadPendingSelectors: [
      '[class*="uploading"]',
      '[class*="progress"]:not([style*="display: none"])',
      'text=/上传中|正在上传/',
    ],
    titleSelectors: [
      'input[placeholder*="填写标题"]',
      'input[placeholder*="标题"]',
      'textarea[placeholder*="标题"]',
    ],
    contentSelectors: [
      '[contenteditable="true"][data-placeholder*="正文"]',
      '[contenteditable="true"]',
      'textarea[placeholder*="正文"]',
      'textarea[placeholder*="描述"]',
      "textarea",
    ],
    draftSelectors: [
      'button:text-is("暂存离开")',
      'button:text-is("保存草稿")',
      'button:has-text("暂存离开")',
      'button:has-text("保存草稿")',
      'button:has-text("存草稿")',
      '[role="button"]:has-text("保存草稿")',
    ],
    publishSelectors: [
      'button:text-is("发布")',
      '[role="button"]:text-is("发布")',
      'button:has-text("发布")',
      '[role="button"]:has-text("发布")',
      "button.ce-btn.bg-red",
    ],
    publicLinkSelectors: [
      'a[href*="xiaohongshu.com/explore/"]',
      'a[href*="xiaohongshu.com/discovery/item/"]',
      'a[href*="xhslink.com/"]',
    ],
    loginUrlMarkers: ["/login", "passport"],
    draftSuccessTexts: ["草稿已保存", "保存草稿成功", "已保存到草稿箱", "已存入草稿箱", "保存成功"],
    submittedTexts: ["发布成功", "提交成功", "审核中", "审核中，请耐心等待", "已提交审核"],
    failureTexts: ["发布失败", "提交失败", "审核不通过", "内容不符合", "内容违规", "已驳回"],
  },
  douyin: {
    platformKey: "douyin",
    editorUrl: "https://creator.douyin.com/creator-micro/content/upload",
    sessionCookieNames: ["sessionid", "sid_tt"],
    sessionOriginHosts: ["creator.douyin.com", "douyin.com"],
    titleLimit: 30,
    contentLimit: 1_000,
    tagLimit: 8,
    imageLimit: 9,
    tabSelectors: [
      '[role="tab"]:has-text("发布图文")',
      '[role="tab"]:has-text("图文")',
      '[class*="tab-item"]:has-text("发布图文")',
      '[class*="tab-item"]:has-text("图文")',
    ],
    uploadSelectors: [
      'input[type="file"][multiple]:not([accept*="video"])',
      'input[type="file"][accept*="image"]',
    ],
    previewSelectors: [
      '[class*="image-list"] [class*="image-item"]',
      '[class*="imageList"] [class*="imageItem"]',
      '[class*="material-list"] [class*="material-item"]',
      '[class*="upload-item"] img',
      'img[src^="blob:"]',
    ],
    uploadPendingSelectors: [
      '[class*="uploading"]',
      '[class*="progress"]:not([style*="display: none"])',
      'text=/上传中|正在上传|处理中/',
    ],
    titleSelectors: [
      'input[placeholder="添加作品标题"]',
      'input[placeholder*="作品标题"]',
      'input[placeholder*="标题"]',
      'textarea[placeholder*="标题"]',
    ],
    contentSelectors: [
      '.zone-container.editor-kit-container[contenteditable="true"]',
      '.zone-container.editor-kit-container',
      '[contenteditable="true"][data-placeholder*="作品描述"]',
      '[contenteditable="true"]',
      'textarea[placeholder*="作品描述"]',
      "textarea",
    ],
    draftSelectors: [
      'button:text-is("保存草稿")',
      'button:text-is("暂存草稿")',
      'button:has-text("保存草稿")',
      'button:has-text("暂存草稿")',
      'button:has-text("存草稿")',
      '[role="button"]:has-text("保存草稿")',
    ],
    publishSelectors: [
      'button:text-is("发布")',
      '[role="button"]:text-is("发布")',
      'button:has-text("发布")',
      '[role="button"]:has-text("发布")',
    ],
    publicLinkSelectors: [
      'a[href*="douyin.com/note/"]',
      'a[href*="douyin.com/video/"]',
    ],
    loginUrlMarkers: ["/login", "passport"],
    draftSuccessTexts: ["草稿已保存", "保存草稿成功", "已保存至草稿箱", "已存入草稿箱", "保存成功"],
    submittedTexts: ["发布成功", "提交成功", "审核中", "作品审核中", "已提交审核"],
    failureTexts: ["发布失败", "提交失败", "审核不通过", "作品违规", "内容不符合", "已驳回"],
  },
};

function experimental(platformKey: SocialPlatformKey) {
  return new Set(
    (process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS || "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  ).has(platformKey);
}

function truncateUnicode(value: string, limit: number) {
  return Array.from(value.trim()).slice(0, limit).join("");
}

function plainText(value: string) {
  return value.replace(/\s+/g, " ").trim();
}

function normalizedTags(tags: readonly string[], limit: number) {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of tags) {
    const tag = truncateUnicode(raw.replace(/^#+/, "").replace(/[\r\n#]/g, " "), 24).trim();
    if (!tag || seen.has(tag)) continue;
    seen.add(tag);
    result.push(tag);
    if (result.length >= limit) break;
  }
  return result;
}

function prepareFields(config: SocialPlatformConfig, input: Pick<PublicationInput, "title" | "contentText" | "contentHtml" | "tags">) {
  const title = truncateUnicode(input.title, config.titleLimit);
  const sourceText = input.contentText.trim() || input.contentHtml.replace(/<[^>]+>/g, " ").trim();
  const content = truncateUnicode(sourceText, config.contentLimit);
  if (!title) return { ok: false as const, safeErrorCode: "content_rejected" };
  if (!plainText(content)) return { ok: false as const, safeErrorCode: "content_rejected" };
  const tags = normalizedTags(input.tags, config.tagLimit);
  const tagLine = tags.map((tag) => `#${tag}`).join(" ");
  const bodyLimit = Math.max(1, config.contentLimit - (tagLine ? Array.from(tagLine).length + 1 : 0));
  const body = truncateUnicode(content, bodyLimit);
  return {
    ok: true as const,
    title,
    body: tagLine ? `${body}\n${tagLine}` : body,
    tags,
  };
}

function hasStoredSession(credentials: PlatformCredentials, config: SocialPlatformConfig) {
  const cookieSession = credentials.cookies?.some(
    (cookie) => config.sessionCookieNames.includes(cookie.name) && Boolean(cookie.value),
  );
  const originSession = credentials.origins?.some((origin) => {
    try {
      const hostname = new URL(origin.origin).hostname.toLowerCase();
      return config.sessionOriginHosts.some(
        (allowed) => hostname === allowed || hostname.endsWith(`.${allowed}`),
      ) && origin.localStorage.some((entry) => Boolean(entry.name && entry.value));
    } catch {
      return false;
    }
  });
  return Boolean(cookieSession || originSession);
}

function validateAssetUrl(value: string) {
  try {
    const url = new URL(value);
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password;
  } catch {
    return false;
  }
}

function imageExtension(bytes: Buffer, contentType: string) {
  if (bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff) return ".jpg";
  if (bytes.length >= 8 && bytes.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return ".png";
  if (bytes.length >= 12 && bytes.subarray(0, 4).toString("ascii") === "RIFF" && bytes.subarray(8, 12).toString("ascii") === "WEBP") return ".webp";
  if (!contentType.toLowerCase().startsWith("image/")) return "";
  return "";
}

async function localAssets(assets: readonly PublicationAsset[], maxFiles: number) {
  const selected: PublicationAsset[] = [];
  const seen = new Set<string>();
  for (const asset of assets) {
    if (!validateAssetUrl(asset.url) || seen.has(asset.url)) continue;
    seen.add(asset.url);
    selected.push(asset);
    if (selected.length >= maxFiles) break;
  }
  if (!selected.length) throw new Error("media_invalid");

  const dir = await mkdtemp(path.join(os.tmpdir(), "xianwen-social-"));
  const files: string[] = [];
  let totalBytes = 0;
  try {
    for (let index = 0; index < selected.length; index += 1) {
      const response = await fetch(selected[index].url, {
        redirect: "follow",
        signal: AbortSignal.timeout(DOWNLOAD_TIMEOUT_MS),
      });
      if (!response.ok) throw new Error("media_download_failed");
      const declaredLength = Number(response.headers.get("content-length") || "0");
      if (Number.isFinite(declaredLength) && declaredLength > MAX_IMAGE_BYTES) throw new Error("media_invalid");
      const bytes = Buffer.from(await response.arrayBuffer());
      const extension = imageExtension(bytes, response.headers.get("content-type") || "");
      if (!extension || bytes.length === 0 || bytes.length > MAX_IMAGE_BYTES) throw new Error("media_invalid");
      totalBytes += bytes.length;
      if (totalBytes > MAX_TOTAL_IMAGE_BYTES) throw new Error("media_invalid");
      const filename = path.join(dir, `image-${index + 1}${extension}`);
      await writeFile(filename, bytes, { flag: "wx" });
      files.push(filename);
    }
    return { dir, files };
  } catch (error) {
    await rm(dir, { recursive: true, force: true });
    throw error;
  }
}

async function firstVisible(page: Page, selectors: readonly string[], timeout = 1_200): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if (await locator.isVisible({ timeout }).catch(() => false)) return locator;
  }
  return null;
}

async function firstAttached(page: Page, selectors: readonly string[]): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = page.locator(selector).first();
    if ((await locator.count().catch(() => 0)) > 0) return locator;
  }
  return null;
}

async function pageText(page: Page) {
  return ((await page.locator("body").innerText().catch(() => "")) || "").slice(-50_000);
}

function includesAny(value: string, candidates: readonly string[]) {
  return candidates.some((candidate) => value.includes(candidate));
}

function classifyFailureText(body: string, config: SocialPlatformConfig) {
  if (includesAny(body, REQUIRED_FIELD_TEXTS)) return "content_rejected";
  if (includesAny(body, MEDIA_FAILURE_TEXTS)) return "media_invalid";
  if (includesAny(body, config.failureTexts)) return "content_rejected";
  return "";
}

async function loginRequired(page: Page, config: SocialPlatformConfig) {
  const currentUrl = page.url().toLowerCase();
  if (config.loginUrlMarkers.some((marker) => currentUrl.includes(marker))) return true;
  const loginForm = page.locator('input[type="password"], input[placeholder*="手机号"], [class*="login"] [class*="qrcode"]').first();
  return loginForm.isVisible({ timeout: 800 }).catch(() => false);
}

function hostnameAllowed(hostname: string, allowed: readonly string[]) {
  const normalized = hostname.toLowerCase();
  return allowed.some((item) => normalized === item || normalized.endsWith(`.${item}`));
}

function safePlatformUrl(platformKey: SocialPlatformKey, value: string, purpose: "management" | "public") {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return false;
    const hostname = url.hostname.toLowerCase();
    if (purpose === "management") {
      return platformKey === "xiaohongshu"
        ? hostnameAllowed(hostname, ["creator.xiaohongshu.com"])
        : hostnameAllowed(hostname, ["creator.douyin.com"]);
    }
    if (platformKey === "xiaohongshu") {
      return (
        hostnameAllowed(hostname, ["xiaohongshu.com", "xhslink.com"]) &&
        (hostname.endsWith("xhslink.com") || /\/(?:explore|discovery\/item)\//.test(url.pathname))
      );
    }
    return hostnameAllowed(hostname, ["douyin.com"]) && /\/(?:note|video)\//.test(url.pathname);
  } catch {
    return false;
  }
}

function sanitizedUrl(value: string) {
  try {
    const url = new URL(value);
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (/(?:token|secret|session|auth|ticket|code)/i.test(key)) url.searchParams.delete(key);
    }
    return url.toString();
  } catch {
    return "";
  }
}

function validExternalPostId(platformKey: SocialPlatformKey, value: string) {
  return platformKey === "xiaohongshu"
    ? /^[A-Fa-f0-9]{16,64}$/.test(value)
    : /^\d{12,32}$/.test(value);
}

function extractExternalPostId(platformKey: SocialPlatformKey, value: string | undefined) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    for (const key of ["noteId", "note_id", "itemId", "item_id", "awemeId", "aweme_id", "group_id", "id"]) {
      const candidate = url.searchParams.get(key) || "";
      if (validExternalPostId(platformKey, candidate)) return candidate;
    }
    const parts = url.pathname.split("/").filter(Boolean).reverse();
    return parts.find((part) => validExternalPostId(platformKey, part));
  } catch {
    return undefined;
  }
}

function titleMatches(value: string, expectedTitle: string | undefined) {
  if (!expectedTitle) return true;
  const observed = plainText(value);
  const expected = plainText(expectedTitle);
  // A result row may contain status text around its title, so exact equality is
  // too strict. The complete platform-truncated expected title must still be
  // present; a short observed fragment is never sufficient evidence.
  return Boolean(observed && expected && observed.includes(expected));
}

async function publicUrls(page: Page, config: SocialPlatformConfig) {
  const current = page.url();
  const results: Array<{ url: string; context: string }> = [];
  if (safePlatformUrl(config.platformKey, current, "public")) {
    results.push({ url: sanitizedUrl(current), context: await pageText(page) });
  }
  for (const selector of config.publicLinkSelectors) {
    const locators = page.locator(selector);
    const count = Math.min(await locators.count().catch(() => 0), 30);
    for (let index = 0; index < count; index += 1) {
      const locator = locators.nth(index);
      const href = await locator.getAttribute("href").catch(() => null);
      if (!href) continue;
      const absolute = new URL(href, current).toString();
      if (!safePlatformUrl(config.platformKey, absolute, "public")) continue;
      const ownText = await locator.innerText().catch(() => "");
      const rowText = await locator.locator("xpath=ancestor::*[self::li or self::article or @role='row'][1]")
        .innerText()
        .catch(() => "");
      results.push({ url: sanitizedUrl(absolute), context: `${ownText}\n${rowText}` });
    }
  }
  return results;
}

async function detectPublicUrl(
  page: Page,
  config: SocialPlatformConfig,
  options: { expectedExternalId?: string; expectedTitle?: string; excludeUrls?: ReadonlySet<string> } = {},
) {
  const candidates = await publicUrls(page, config);
  return candidates.find((candidate) => {
    if (options.excludeUrls?.has(candidate.url)) return false;
    if (
      options.expectedExternalId &&
      extractExternalPostId(config.platformKey, candidate.url) !== options.expectedExternalId
    ) return false;
    return titleMatches(candidate.context, options.expectedTitle);
  })?.url;
}

async function visibleCount(page: Page, selectors: readonly string[]) {
  let maximum = 0;
  for (const selector of selectors) {
    const locators = page.locator(selector);
    const count = await locators.count().catch(() => 0);
    let visible = 0;
    for (let index = 0; index < count; index += 1) {
      if (await locators.nth(index).isVisible().catch(() => false)) visible += 1;
    }
    maximum = Math.max(maximum, visible);
  }
  return maximum;
}

async function waitForImageUploads(page: Page, config: SocialPlatformConfig, expected: number) {
  const deadline = Date.now() + UPLOAD_TIMEOUT_MS;
  let stableChecks = 0;
  while (Date.now() < deadline) {
    const body = await pageText(page);
    const failure = classifyFailureText(body, config);
    if (failure) return { ok: false as const, safeErrorCode: failure };
    const pending = await visibleCount(page, config.uploadPendingSelectors);
    const previews = await visibleCount(page, config.previewSelectors);
    if (pending === 0 && previews >= expected) {
      stableChecks += 1;
      if (stableChecks >= 2) return { ok: true as const };
    } else {
      stableChecks = 0;
    }
    await page.waitForTimeout(750);
  }
  return { ok: false as const, safeErrorCode: "media_invalid" };
}

async function fieldValue(locator: Locator) {
  const tagName = await locator.evaluate((element) => element.tagName.toLowerCase()).catch(() => "");
  if (["input", "textarea"].includes(tagName)) return locator.inputValue().catch(() => "");
  return locator.innerText().catch(() => "");
}

async function fillAndVerify(locator: Locator, expected: string) {
  let target = locator;
  const tagName = await locator.evaluate((element) => element.tagName.toLowerCase()).catch(() => "");
  const editable = await locator.getAttribute("contenteditable").catch(() => null);
  if (!["input", "textarea"].includes(tagName) && editable !== "true") {
    const nested = locator.locator('[contenteditable="true"], textarea, input').first();
    if (!(await nested.isVisible({ timeout: 800 }).catch(() => false))) return false;
    target = nested;
  }
  await target.fill(expected);
  const observed = plainText(await fieldValue(target));
  const reference = plainText(expected);
  return Boolean(observed && reference && (observed.includes(reference.slice(0, 24)) || reference.includes(observed)));
}

async function clickConfirmation(page: Page, mode: "draft" | "public") {
  const dialogs = page.locator('[role="dialog"], [class*="modal"], [class*="dialog"]');
  const count = await dialogs.count().catch(() => 0);
  const names = mode === "draft"
    ? /^(确认保存|保存草稿|暂存离开|确定)$/
    : /^(确认发布|立即发布|发布|确定)$/;
  for (let index = count - 1; index >= 0; index -= 1) {
    const dialog = dialogs.nth(index);
    if (!(await dialog.isVisible().catch(() => false))) continue;
    const confirm = dialog.getByRole("button", { name: names }).last();
    if (await confirm.isVisible({ timeout: 600 }).catch(() => false)) {
      if (!(await confirm.isDisabled().catch(() => true))) await confirm.click();
      return;
    }
  }
}

async function clickAction(page: Page, selectors: readonly string[], mode: "draft" | "public") {
  const action = await firstVisible(page, selectors, 1_500);
  if (!action || (await action.isDisabled().catch(() => true))) return false;
  await action.scrollIntoViewIfNeeded().catch(() => undefined);
  await action.click();
  await page.waitForTimeout(700);
  await clickConfirmation(page, mode);
  return true;
}

async function saveAndReviewDraft(page: Page, config: SocialPlatformConfig, expectedTitle: string) {
  if (!(await clickAction(page, config.draftSelectors, "draft"))) {
    return { ok: false as const, safeErrorCode: "publish_control_changed", managementUrl: sanitizedUrl(page.url()) };
  }
  await page.waitForTimeout(1_500);
  if (await loginRequired(page, config)) {
    return { ok: false as const, safeErrorCode: "authorization_required", authRequired: true as const };
  }
  let body = await pageText(page);
  const failure = classifyFailureText(body, config);
  if (failure) return { ok: false as const, safeErrorCode: failure, managementUrl: sanitizedUrl(page.url()) };
  const saveEvidence = includesAny(body, config.draftSuccessTexts);
  const currentUrl = sanitizedUrl(page.url());

  // Reloading is intentional: unsaved editor state disappears, while a real saved
  // draft retains its title or redirects to a draft-management row. This prevents
  // reporting a draft merely because fields were filled in memory.
  const reloaded = await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 })
    .then(() => true)
    .catch(() => false);
  if (!reloaded) {
    return { ok: false as const, safeErrorCode: "publish_result_unconfirmed", managementUrl: currentUrl };
  }
  await page.waitForTimeout(1_200);
  if (await loginRequired(page, config)) {
    return { ok: false as const, safeErrorCode: "authorization_required", authRequired: true as const };
  }
  body = await pageText(page);
  const reloadedTitle = await firstVisible(page, config.titleSelectors, 1_200);
  const observed = reloadedTitle ? plainText(await fieldValue(reloadedTitle)) : "";
  const normalizedExpected = plainText(expectedTitle);
  const titleProof = observed === normalizedExpected || plainText(body).includes(normalizedExpected);
  if (titleProof && (saveEvidence || safePlatformUrl(config.platformKey, page.url(), "management"))) {
    const reviewedUrl = sanitizedUrl(page.url());
    return { ok: true as const, editUrl: reviewedUrl, managementUrl: reviewedUrl };
  }
  return { ok: false as const, safeErrorCode: "publish_result_unconfirmed", managementUrl: currentUrl };
}

async function publicResult(
  page: Page,
  config: SocialPlatformConfig,
  baselineBody: string,
  baselineUrls: ReadonlySet<string>,
  expectedTitle: string,
): Promise<PublicationResult> {
  const deadline = Date.now() + 15_000;
  do {
    const managementUrl = safePlatformUrl(config.platformKey, page.url(), "management")
      ? sanitizedUrl(page.url())
      : undefined;
    if (await loginRequired(page, config)) {
      return { success: false, platformKey: config.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    const body = await pageText(page);
    const failure = classifyFailureText(body, config);
    if (failure && !classifyFailureText(baselineBody, config)) {
      return { success: false, platformKey: config.platformKey, status: "failed", managementUrl, safeErrorCode: failure };
    }
    const submittedEvidence = config.submittedTexts.some(
      (value) => body.includes(value) && !baselineBody.includes(value),
    );
    const currentIsPublic = safePlatformUrl(config.platformKey, page.url(), "public");
    const publicUrl = submittedEvidence || currentIsPublic
      ? await detectPublicUrl(page, config, { expectedTitle, excludeUrls: baselineUrls })
      : undefined;
    if (publicUrl) {
      return {
        success: true,
        platformKey: config.platformKey,
        status: "published",
        externalPostId: extractExternalPostId(config.platformKey, publicUrl),
        publicUrl,
        managementUrl,
      };
    }
    const submittedId = extractExternalPostId(config.platformKey, page.url());
    if (submittedEvidence && submittedId) {
      return { success: true, platformKey: config.platformKey, status: "submitted", externalPostId: submittedId, managementUrl };
    }
    if (Date.now() >= deadline) break;
    await page.waitForTimeout(750);
  } while (true);
  return {
    success: false,
    platformKey: config.platformKey,
    status: "action_required",
    managementUrl: safePlatformUrl(config.platformKey, page.url(), "management")
      ? sanitizedUrl(page.url())
      : undefined,
    safeErrorCode: "publish_result_unconfirmed",
  };
}

async function runStatusCheck(config: SocialPlatformConfig, input: PublicationStatusInput): Promise<PublicationStatusResult> {
  if (!experimental(config.platformKey)) return { platformKey: config.platformKey, status: "unknown" };
  if (!hasStoredSession(input.credentials, config)) {
    return { platformKey: config.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
  }

  const requestedExternalId = input.externalPostId && validExternalPostId(config.platformKey, input.externalPostId)
    ? input.externalPostId
    : undefined;
  let targetUrl = input.managementUrl || "";
  if (requestedExternalId) {
    targetUrl = config.platformKey === "xiaohongshu"
      ? `https://www.xiaohongshu.com/explore/${requestedExternalId}`
      : `https://www.douyin.com/note/${requestedExternalId}`;
  }
  const allowed = safePlatformUrl(config.platformKey, targetUrl, "management") || safePlatformUrl(config.platformKey, targetUrl, "public");
  if (!allowed) return { platformKey: config.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };

  const { browser, context } = await createPublisherBrowserContext(input.credentials);
  try {
    const page = await context.newPage();
    await page.goto(targetUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_500);
    if (await loginRequired(page, config)) {
      return { platformKey: config.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    const managementUrl = safePlatformUrl(config.platformKey, page.url(), "management")
      ? sanitizedUrl(page.url())
      : undefined;
    const body = await pageText(page);
    const failure = classifyFailureText(body, config);
    if (failure) {
      return { platformKey: config.platformKey, status: "failed", managementUrl, safeErrorCode: failure };
    }
    const referenceId = requestedExternalId || extractExternalPostId(config.platformKey, targetUrl);
    const publicUrl = await detectPublicUrl(page, config, {
      expectedExternalId: referenceId,
      expectedTitle: referenceId ? undefined : input.expectedTitle,
    });
    if (publicUrl) return { platformKey: config.platformKey, status: "published", publicUrl, managementUrl };
    if (referenceId && includesAny(body, [...config.submittedTexts, "待审核", "处理中", "审核通过", "已发布"])) {
      return { platformKey: config.platformKey, status: "submitted", managementUrl };
    }
    return { platformKey: config.platformKey, status: "unknown", managementUrl };
  } catch {
    return { platformKey: config.platformKey, status: "unknown", safeErrorCode: "platform_unavailable" };
  } finally {
    await context.close().catch(() => undefined);
    await browser.close().catch(() => undefined);
  }
}

async function runAuthCheck(config: SocialPlatformConfig, credentials: PlatformCredentials) {
  if (!hasStoredSession(credentials, config)) return { ok: false };
  const { browser, context } = await createPublisherBrowserContext(credentials);
  try {
    const page = await context.newPage();
    await page.goto(config.editorUrl, { waitUntil: "domcontentloaded", timeout: 45_000 });
    await page.waitForTimeout(1_200);
    if (await loginRequired(page, config)) return { ok: false };
    const tab = await firstVisible(page, config.tabSelectors, 700);
    if (tab) {
      await tab.click();
      await page.waitForTimeout(500);
    }
    const upload = await firstAttached(page, config.uploadSelectors);
    const editor = await firstVisible(page, [...config.titleSelectors, ...config.contentSelectors], 1_200);
    return { ok: Boolean(upload || editor) };
  } catch {
    return { ok: false };
  } finally {
    await context.close().catch(() => undefined);
    await browser.close().catch(() => undefined);
  }
}

async function runPublish(config: SocialPlatformConfig, input: PublicationInput): Promise<PublicationResult> {
  if (!experimental(config.platformKey)) {
    return { success: false, platformKey: config.platformKey, status: "action_required", safeErrorCode: "platform_not_verified" };
  }
  if (!hasStoredSession(input.credentials, config)) {
    return { success: false, platformKey: config.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
  }
  const fields = prepareFields(config, input);
  if (!fields.ok) {
    return { success: false, platformKey: config.platformKey, status: "failed", safeErrorCode: fields.safeErrorCode };
  }
  if (!input.assets.length) {
    return { success: false, platformKey: config.platformKey, status: "failed", safeErrorCode: "media_invalid" };
  }

  let dir = "";
  let browser: Awaited<ReturnType<typeof createPublisherBrowserContext>>["browser"] | null = null;
  let context: Awaited<ReturnType<typeof createPublisherBrowserContext>>["context"] | null = null;
  try {
    const local = await localAssets(input.assets, config.imageLimit);
    dir = local.dir;
    ({ browser, context } = await createPublisherBrowserContext(input.credentials));
    const page = await context.newPage();
    await page.goto(config.editorUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
    await page.waitForTimeout(1_600);
    if (await loginRequired(page, config)) {
      return { success: false, platformKey: config.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }

    const tab = await firstVisible(page, config.tabSelectors, 900);
    if (tab) {
      await tab.click();
      await page.waitForTimeout(700);
    }
    const upload = await firstAttached(page, config.uploadSelectors);
    if (!upload) {
      return { success: false, platformKey: config.platformKey, status: "action_required", managementUrl: sanitizedUrl(page.url()), safeErrorCode: "editor_changed" };
    }
    if (local.files.length > 1 && (await upload.getAttribute("multiple")) === null) {
      return { success: false, platformKey: config.platformKey, status: "action_required", managementUrl: sanitizedUrl(page.url()), safeErrorCode: "editor_changed" };
    }
    await upload.setInputFiles(local.files);
    const uploadResult = await waitForImageUploads(page, config, local.files.length);
    if (!uploadResult.ok) {
      return { success: false, platformKey: config.platformKey, status: "failed", managementUrl: sanitizedUrl(page.url()), safeErrorCode: uploadResult.safeErrorCode };
    }

    const title = await firstVisible(page, config.titleSelectors, 15_000);
    const content = await firstVisible(page, config.contentSelectors, 5_000);
    if (!title || !content) {
      return { success: false, platformKey: config.platformKey, status: "action_required", managementUrl: sanitizedUrl(page.url()), safeErrorCode: "editor_changed" };
    }
    if (!(await fillAndVerify(title, fields.title)) || !(await fillAndVerify(content, fields.body))) {
      return { success: false, platformKey: config.platformKey, status: "action_required", managementUrl: sanitizedUrl(page.url()), safeErrorCode: "editor_changed" };
    }

    const validationFailure = classifyFailureText(await pageText(page), config);
    if (validationFailure) {
      return { success: false, platformKey: config.platformKey, status: "failed", managementUrl: sanitizedUrl(page.url()), safeErrorCode: validationFailure };
    }

    if (input.publishMode === "draft") {
      const result = await saveAndReviewDraft(page, config, fields.title);
      if (!result.ok) {
        return {
          success: false,
          platformKey: config.platformKey,
          status: result.authRequired ? "auth_required" : "action_required",
          managementUrl: result.managementUrl,
          safeErrorCode: result.safeErrorCode,
        };
      }
      return {
        success: true,
        platformKey: config.platformKey,
        status: "drafted",
        editUrl: result.editUrl,
        managementUrl: result.managementUrl,
      };
    }

    const baselineBody = await pageText(page);
    const baselineUrls = new Set((await publicUrls(page, config)).map((item) => item.url));
    if (!(await clickAction(page, config.publishSelectors, "public"))) {
      return { success: false, platformKey: config.platformKey, status: "action_required", managementUrl: sanitizedUrl(page.url()), safeErrorCode: "publish_control_changed" };
    }
    return publicResult(page, config, baselineBody, baselineUrls, fields.title);
  } catch (error) {
    const code = error instanceof Error ? error.message : "platform_unavailable";
    const deterministicMediaError = code === "media_invalid";
    return {
      success: false,
      platformKey: config.platformKey,
      status: deterministicMediaError ? "failed" : "action_required",
      safeErrorCode: deterministicMediaError ? "media_invalid" : "platform_unavailable",
    };
  } finally {
    if (context) await context.close().catch(() => undefined);
    if (browser) await browser.close().catch(() => undefined);
    if (dir) await rm(dir, { recursive: true, force: true });
  }
}

export const __socialImageTestables = {
  truncateUnicode,
  normalizedTags,
  prepareFields: (platformKey: SocialPlatformKey, input: Pick<PublicationInput, "title" | "contentText" | "contentHtml" | "tags">) =>
    prepareFields(CONFIGS[platformKey], input),
  classifyFailureText: (platformKey: SocialPlatformKey, body: string) => classifyFailureText(body, CONFIGS[platformKey]),
  safePlatformUrl,
  sanitizedUrl,
  extractExternalPostId,
  titleMatches,
  validateAssetUrl,
  hasStoredSession: (platformKey: SocialPlatformKey, credentials: PlatformCredentials) => hasStoredSession(credentials, CONFIGS[platformKey]),
};

export class XiaohongshuPublisher implements PlatformPublisher {
  readonly platformKey = "xiaohongshu";
  // Candidate implementation only. Real-account acceptance must expand this list.
  readonly verifiedCapabilities = ["auth"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    return runAuthCheck(CONFIGS.xiaohongshu, credentials);
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    return runStatusCheck(CONFIGS.xiaohongshu, input);
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    return runPublish(CONFIGS.xiaohongshu, input);
  }
}

export class DouyinImagePublisher implements PlatformPublisher {
  readonly platformKey = "douyin";
  // Candidate implementation only. Real-account acceptance must expand this list.
  readonly verifiedCapabilities = ["auth"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    return runAuthCheck(CONFIGS.douyin, credentials);
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    return runStatusCheck(CONFIGS.douyin, input);
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    return runPublish(CONFIGS.douyin, input);
  }
}
