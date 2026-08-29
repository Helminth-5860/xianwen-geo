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

export const BROWSER_SAFE_ERROR_MESSAGES = {
  platform_not_verified: "该平台尚未完成真实账号验收",
  authorization_required: "平台授权已失效，请重新授权",
  unsafe_status_url: "状态回查地址不属于该平台的安全地址",
  editor_changed: "平台编辑器已改版，需要重新适配",
  draft_control_changed: "未找到平台草稿保存入口",
  draft_save_unconfirmed: "平台没有返回可确认的草稿保存结果",
  publish_control_changed: "未找到平台发布入口或确认步骤",
  publish_result_unconfirmed: "平台没有返回可确认的发布结果",
  status_target_unbound: "无法确认本次文章对应的平台记录",
  platform_fields_required: "平台仍有必填项需要人工确认",
  content_rejected: "内容被平台拒绝或审核不通过",
  media_invalid: "图片无效或不符合平台要求",
  platform_unavailable: "平台暂时不可用，请稍后重试",
} as const;

export type BrowserSafeErrorCode = keyof typeof BROWSER_SAFE_ERROR_MESSAGES;

export type BrowserClickStep = Readonly<{
  name: string;
  selectors: readonly string[];
  optional?: boolean;
  waitAfterMs?: number;
}>;

export type BrowserDraftStrategy = Readonly<{
  actionSelectors?: readonly string[];
  autoSaveWaitMs?: number;
  successSelectors?: readonly string[];
  successTexts: readonly string[];
  urlPatterns?: readonly RegExp[];
}>;

export type BrowserTagStrategy = Readonly<{
  required?: boolean;
  phase?: "editor" | "publish_dialog";
  triggerSelectors?: readonly string[];
  inputSelectors: readonly string[];
  maxTags?: number;
  waitAfterEachMs?: number;
}>;

export type BrowserPublisherConfig = Readonly<{
  platformKey: string;
  editorUrl: string;
  authCookieNames: readonly string[];
  loginMarkers?: readonly string[];
  loginSelectors?: readonly string[];
  titleSelectors: readonly string[];
  contentSelectors: readonly string[];
  titleLimit?: number;
  contentLimit?: number;
  tagStrategy?: BrowserTagStrategy;
  coverTriggerTexts?: readonly string[];
  coverInputSelectors?: readonly string[];
  coverRequired?: boolean;
  draft: BrowserDraftStrategy;
  publishSteps: readonly BrowserClickStep[];
  successTexts: readonly string[];
  reviewTexts?: readonly string[];
  failureTexts?: readonly string[];
  validationTexts?: readonly string[];
  publicLinkSelectors: readonly string[];
  statusItemSelectors?: readonly string[];
  statusTitleSelectors?: readonly string[];
  publicUrlPatterns: readonly RegExp[];
  statusUrlPatterns: readonly RegExp[];
  allowedHostSuffixes: readonly string[];
  resultTimeoutMs?: number;
}>;

type PageEvidence = Readonly<{
  kind: "published" | "submitted" | "failed" | "action_required" | "unknown";
  publicUrl?: string;
  safeErrorCode?: BrowserSafeErrorCode;
}>;

const DEFAULT_LOGIN_MARKERS = ["login", "signin", "passport", "account"] as const;
const DEFAULT_FAILURE_TEXTS = ["发布失败", "提交失败", "审核不通过", "已驳回", "未通过"] as const;
const DEFAULT_STATUS_FAILURE_SELECTORS = [
  '[data-status="rejected"]',
  '[data-status="failed"]',
  '[class*="status"]:has-text("审核不通过")',
  '[class*="status"]:has-text("已驳回")',
  '[class*="state"]:has-text("审核不通过")',
] as const;
const DEFAULT_STATUS_REVIEW_SELECTORS = [
  '[data-status="reviewing"]',
  '[data-status="pending"]',
  '[class*="status"]:has-text("审核中")',
  '[class*="status"]:has-text("待审核")',
  '[class*="state"]:has-text("审核中")',
] as const;
const DEFAULT_STATUS_PUBLISHED_SELECTORS = [
  '[data-status="published"]',
  '[class*="status"]:has-text("已发布")',
  '[class*="state"]:has-text("已发布")',
] as const;

function boundedWait(value: number | undefined, fallback: number) {
  if (!Number.isFinite(value)) return fallback;
  return Math.max(0, Math.min(30_000, Math.trunc(value || 0)));
}

function enabledPlatformKeys() {
  return new Set(
    (process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS || "")
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean),
  );
}

function matchesAny(value: string, patterns: readonly RegExp[]) {
  return patterns.some((pattern) => {
    pattern.lastIndex = 0;
    return pattern.test(value);
  });
}

function safeHttpsUrl(value: string) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    if (url.port && url.port !== "443") return null;
    return url;
  } catch {
    return null;
  }
}

function hostAllowed(hostname: string, suffixes: readonly string[]) {
  const normalized = hostname.toLowerCase().replace(/\.$/, "");
  return suffixes.some((item) => {
    const suffix = item.toLowerCase().replace(/^\./, "").replace(/\.$/, "");
    return normalized === suffix || normalized.endsWith(`.${suffix}`);
  });
}

function normalizedComparableText(value: string) {
  return value.normalize("NFKC").replace(/\s+/g, " ").trim();
}

export function exactStatusTitleMatch(observed: string, expected: string) {
  const normalizedObserved = normalizedComparableText(observed);
  const normalizedExpected = normalizedComparableText(expected);
  return Boolean(normalizedObserved && normalizedExpected && normalizedObserved === normalizedExpected);
}

export function urlContainsExternalPostId(value: string, externalPostId: string) {
  const expected = externalPostId.trim();
  if (!expected) return false;
  const url = safeHttpsUrl(value);
  if (!url) return false;
  const candidates = [
    ...Array.from(url.searchParams.values()),
    ...url.pathname.split(/[\/;,:]+/),
    ...url.hash.replace(/^#/, "").split(/[\/&=;,:]+/),
  ];
  return candidates.some((candidate) => {
    try {
      return decodeURIComponent(candidate).trim() === expected;
    } catch {
      return candidate.trim() === expected;
    }
  });
}

export function isPublicArticleUrl(value: string, config: BrowserPublisherConfig) {
  const url = safeHttpsUrl(value);
  if (!url || !hostAllowed(url.hostname, config.allowedHostSuffixes)) return false;
  return matchesAny(url.href, config.publicUrlPatterns);
}

export function isSafeStatusUrl(value: string, config: BrowserPublisherConfig) {
  const url = safeHttpsUrl(value);
  if (!url || !hostAllowed(url.hostname, config.allowedHostSuffixes)) return false;
  return matchesAny(url.href, [...config.statusUrlPatterns, ...config.publicUrlPatterns]);
}

export function browserSafeErrorMessage(code: BrowserSafeErrorCode) {
  return BROWSER_SAFE_ERROR_MESSAGES[code];
}

export function validateBrowserPublisherConfig(config: BrowserPublisherConfig) {
  const issues: string[] = [];
  if (!config.platformKey.trim()) issues.push("platform_key_required");
  if (!safeHttpsUrl(config.editorUrl)) issues.push("https_editor_url_required");
  if (!config.authCookieNames.length) issues.push("auth_cookie_names_required");
  if (!config.titleSelectors.length || !config.contentSelectors.length) issues.push("editor_selectors_required");
  if (!config.draft.successTexts.length && !config.draft.successSelectors?.length && !config.draft.urlPatterns?.length) {
    issues.push("draft_confirmation_required");
  }
  if (!config.draft.actionSelectors?.length && !config.draft.autoSaveWaitMs) issues.push("draft_action_required");
  if (!config.publishSteps.length || config.publishSteps.some((step) => !step.selectors.length)) {
    issues.push("publish_steps_required");
  }
  if (!config.publicLinkSelectors.length || !config.publicUrlPatterns.length) issues.push("public_url_evidence_required");
  if (!config.statusItemSelectors?.length || !config.statusTitleSelectors?.length) {
    issues.push("status_binding_selectors_required");
  }
  if (!config.statusUrlPatterns.length || !config.allowedHostSuffixes.length) issues.push("safe_status_policy_required");
  if (!isSafeStatusUrl(config.editorUrl, config)) issues.push("editor_url_not_in_status_policy");
  return issues;
}

type LocatorRoot = Pick<Page, "locator"> | Pick<Locator, "locator">;

async function firstVisible(root: LocatorRoot, selectors: readonly string[], timeout = 1200): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = root.locator(selector).first();
    if (await locator.isVisible({ timeout }).catch(() => false)) return locator;
  }
  return null;
}

async function firstAttached(root: LocatorRoot, selectors: readonly string[]): Promise<Locator | null> {
  for (const selector of selectors) {
    const locator = root.locator(selector).first();
    if ((await locator.count().catch(() => 0)) > 0) return locator;
  }
  return null;
}

async function pageText(page: Page) {
  return (await page.locator("body").innerText().catch(() => "")).slice(-40_000);
}

async function locatorValue(locator: Locator) {
  const tagName = await locator.evaluate((element) => element.tagName.toLowerCase()).catch(() => "");
  if (tagName === "input" || tagName === "textarea") return locator.inputValue().catch(() => "");
  return locator.innerText().catch(() => "");
}

async function locatorHasExactTitle(root: LocatorRoot, selectors: readonly string[], expectedTitle: string) {
  for (const selector of selectors) {
    const locators = root.locator(selector);
    const count = Math.min(await locators.count().catch(() => 0), 100);
    for (let index = 0; index < count; index += 1) {
      const locator = locators.nth(index);
      if (!(await locator.isVisible().catch(() => false))) continue;
      if (exactStatusTitleMatch(await locatorValue(locator), expectedTitle)) return true;
    }
  }
  return false;
}

function hasText(body: string, values: readonly string[]) {
  return values.some((value) => value && body.includes(value));
}

function hasAuthCookie(credentials: PlatformCredentials, config: BrowserPublisherConfig) {
  return Boolean(
    credentials.cookies?.some(
      (cookie) => config.authCookieNames.includes(cookie.name) && Boolean(cookie.value),
    ),
  );
}

async function looksLoggedOut(page: Page, config: BrowserPublisherConfig) {
  const currentUrl = page.url().toLowerCase();
  if ((config.loginMarkers || DEFAULT_LOGIN_MARKERS).some((marker) => currentUrl.includes(marker.toLowerCase()))) {
    return true;
  }
  if (config.loginSelectors?.length) return Boolean(await firstVisible(page, config.loginSelectors, 500));
  return false;
}

async function downloadAsset(asset: PublicationAsset) {
  const response = await fetch(asset.url, { redirect: "follow" });
  if (!response.ok) throw new Error("media_download_failed");
  const bytes = Buffer.from(await response.arrayBuffer());
  if (bytes.length === 0 || bytes.length > 15 * 1024 * 1024) throw new Error("media_invalid");
  const contentType = response.headers.get("content-type") || "image/jpeg";
  if (!contentType.toLowerCase().startsWith("image/")) throw new Error("media_invalid");
  const extension = contentType.includes("png") ? ".png" : contentType.includes("webp") ? ".webp" : ".jpg";
  const dir = await mkdtemp(path.join(os.tmpdir(), "xianwen-publish-"));
  const filename = path.join(dir, `asset${extension}`);
  await writeFile(filename, bytes);
  return { filename, dir };
}

async function uploadCover(page: Page, input: PublicationInput, config: BrowserPublisherConfig) {
  const cover = input.assets.find((item) => item.role === "cover") || input.assets[0];
  if (!cover) return false;
  for (const label of config.coverTriggerTexts || []) {
    const trigger = page.getByText(label, { exact: false }).first();
    if (await trigger.isVisible({ timeout: 800 }).catch(() => false)) {
      await trigger.click();
      await page.waitForTimeout(500);
      break;
    }
  }
  const inputLocator = await firstAttached(page, config.coverInputSelectors || ['input[type="file"]']);
  if (!inputLocator) return false;
  const { filename, dir } = await downloadAsset(cover);
  try {
    await inputLocator.setInputFiles(filename);
    await page.waitForTimeout(1000);
    const confirm = page.getByRole("button", { name: /确定|确认|完成|使用/ }).first();
    if (await confirm.isVisible({ timeout: 700 }).catch(() => false)) {
      await confirm.click();
      await page.waitForTimeout(400);
    }
    return true;
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
}

async function fillTags(page: Page, input: PublicationInput, strategy: BrowserTagStrategy | undefined) {
  if (!strategy) return true;
  const tags = input.tags.map((item) => item.trim()).filter(Boolean).slice(0, strategy.maxTags || 5);
  if (!tags.length) return !strategy.required;
  if (strategy.triggerSelectors?.length) {
    const trigger = await firstVisible(page, strategy.triggerSelectors);
    if (!trigger) return false;
    await trigger.click();
    await page.waitForTimeout(300);
  }
  const inputLocator = await firstVisible(page, strategy.inputSelectors);
  if (!inputLocator) return false;
  for (const tag of tags) {
    const exactLabels = page.getByText(tag, { exact: true });
    const baselineCount = await exactLabels.count().catch(() => 0);
    await inputLocator.fill(tag);
    await page.waitForTimeout(boundedWait(strategy.waitAfterEachMs, 500));
    await inputLocator.press("Enter");
    await page.waitForTimeout(250);
    const confirmedCount = await exactLabels.count().catch(() => 0);
    if (confirmedCount <= baselineCount) return false;
  }
  return true;
}

function resolveLink(href: string, base: string) {
  try {
    return new URL(href, base).href;
  } catch {
    return "";
  }
}

async function detectPublicUrl(
  page: Page,
  config: BrowserPublisherConfig,
  options: {
    allowLinks?: boolean;
    externalPostId?: string;
    expectedTitle?: string;
    scope?: LocatorRoot;
  } = {},
): Promise<string | undefined> {
  const current = page.url();
  const currentBound = options.externalPostId
    ? urlContainsExternalPostId(current, options.externalPostId)
    : options.expectedTitle
      ? await locatorHasExactTitle(page, ["h1", "article h1", '[class*="title"]'], options.expectedTitle)
      : true;
  if (currentBound && isPublicArticleUrl(current, config)) return current;
  if (options.allowLinks === false) return undefined;
  const root = options.scope || page;
  for (const selector of config.publicLinkSelectors) {
    const locators = root.locator(selector);
    const count = Math.min(await locators.count().catch(() => 0), 20);
    for (let index = 0; index < count; index += 1) {
      const locator = locators.nth(index);
      const href = await locator.getAttribute("href").catch(() => null);
      if (!href) continue;
      const resolved = resolveLink(href, current);
      if (options.externalPostId && !urlContainsExternalPostId(resolved, options.externalPostId)) continue;
      if (options.expectedTitle) {
        const ownText = await locator.innerText().catch(() => "");
        if (!exactStatusTitleMatch(ownText, options.expectedTitle)) continue;
      }
      if (isPublicArticleUrl(resolved, config)) return resolved;
    }
  }
  return undefined;
}

async function statusScopeForInput(
  page: Page,
  config: BrowserPublisherConfig,
  input: PublicationStatusInput,
): Promise<LocatorRoot | null> {
  const externalPostId = input.externalPostId?.trim();
  const expectedTitle = input.expectedTitle?.trim();
  if (!externalPostId && !expectedTitle) return null;

  // A direct per-article management/public URL is a valid binding only when its
  // identifier is an exact URL token, never a substring match.
  if (externalPostId && urlContainsExternalPostId(page.url(), externalPostId)) return page;
  const directDraftPage = Boolean(config.draft.urlPatterns?.length && matchesAny(page.url(), config.draft.urlPatterns));
  if (expectedTitle && directDraftPage && await locatorHasExactTitle(page, config.titleSelectors, expectedTitle)) {
    return page;
  }
  if (
    expectedTitle &&
    isPublicArticleUrl(page.url(), config) &&
    await locatorHasExactTitle(page, ["h1", "article h1", '[class*="article-title"]'], expectedTitle)
  ) return page;

  for (const selector of config.statusItemSelectors || []) {
    const rows = page.locator(selector);
    const count = Math.min(await rows.count().catch(() => 0), 100);
    for (let index = 0; index < count; index += 1) {
      const row = rows.nth(index);
      if (!(await row.isVisible().catch(() => false))) continue;
      if (externalPostId) {
        const links = row.locator("a[href]");
        const linkCount = Math.min(await links.count().catch(() => 0), 20);
        for (let linkIndex = 0; linkIndex < linkCount; linkIndex += 1) {
          const href = await links.nth(linkIndex).getAttribute("href").catch(() => null);
          if (!href) continue;
          if (urlContainsExternalPostId(resolveLink(href, page.url()), externalPostId)) return row;
        }
        continue;
      }
      if (expectedTitle && await locatorHasExactTitle(row, config.statusTitleSelectors || [], expectedTitle)) {
        return row;
      }
    }
  }
  return null;
}

export function classifyPageEvidence(
  body: string,
  publicUrl: string | undefined,
  config: BrowserPublisherConfig,
  baselineBody = "",
): PageEvidence {
  const newlyContains = (values: readonly string[]) => values.some(
    (value) => value && body.includes(value) && (!baselineBody || !baselineBody.includes(value)),
  );
  if (newlyContains(config.failureTexts || DEFAULT_FAILURE_TEXTS)) {
    return { kind: "failed", safeErrorCode: "content_rejected" };
  }
  if (newlyContains(config.validationTexts || [])) {
    return { kind: "action_required", safeErrorCode: "platform_fields_required" };
  }
  if (publicUrl && isPublicArticleUrl(publicUrl, config)) return { kind: "published", publicUrl };
  if (newlyContains(config.reviewTexts || [])) return { kind: "submitted" };
  if (newlyContains(config.successTexts)) return { kind: "submitted" };
  return { kind: "unknown" };
}

async function waitForPublicationEvidence(
  page: Page,
  config: BrowserPublisherConfig,
  baselineBody: string,
  baselinePublicUrl: string | undefined,
  expectedTitle: string,
) {
  const timeout = boundedWait(config.resultTimeoutMs, 12_000);
  const deadline = Date.now() + timeout;
  do {
    const body = await pageText(page);
    const visibleValidation = await firstVisible(
      page,
      (config.validationTexts || []).map((value) => `text=${JSON.stringify(value)}`),
      250,
    );
    if (visibleValidation) {
      return { kind: "action_required", safeErrorCode: "platform_fields_required" } as const;
    }
    const publicUrl = await detectPublicUrl(page, config, { expectedTitle });
    const newPublicUrl = publicUrl && publicUrl !== baselinePublicUrl ? publicUrl : undefined;
    const evidence = classifyPageEvidence(body, newPublicUrl, config, baselineBody);
    if (evidence.kind !== "unknown") return evidence;
    if (Date.now() >= deadline) return evidence;
    await page.waitForTimeout(600);
  } while (true);
}

type DraftBaseline = Readonly<{
  body: string;
  url: string;
  successSelectorCounts: readonly number[];
}>;

async function captureDraftBaseline(page: Page, config: BrowserPublisherConfig): Promise<DraftBaseline> {
  const successSelectorCounts: number[] = [];
  for (const selector of config.draft.successSelectors || []) {
    successSelectorCounts.push(await page.locator(selector).count().catch(() => 0));
  }
  return { body: await pageText(page), url: page.url(), successSelectorCounts };
}

async function confirmDraft(page: Page, config: BrowserPublisherConfig, baseline: DraftBaseline) {
  const waitMs = config.draft.actionSelectors?.length
    ? boundedWait(config.draft.autoSaveWaitMs, 1500)
    : boundedWait(config.draft.autoSaveWaitMs, 5000);
  if (waitMs) await page.waitForTimeout(waitMs);
  const body = await pageText(page);
  const newFailure = (config.failureTexts || DEFAULT_FAILURE_TEXTS).some(
    (value) => value && body.includes(value) && !baseline.body.includes(value),
  );
  if (newFailure) {
    return { confirmed: false, failed: true } as const;
  }
  const newSuccessText = config.draft.successTexts.some(
    (value) => value && body.includes(value) && !baseline.body.includes(value),
  );
  if (newSuccessText) return { confirmed: true, failed: false } as const;
  for (let index = 0; index < (config.draft.successSelectors || []).length; index += 1) {
    const selector = config.draft.successSelectors?.[index];
    if (!selector) continue;
    const currentCount = await page.locator(selector).count().catch(() => 0);
    if (currentCount > (baseline.successSelectorCounts[index] || 0)) {
      return { confirmed: true, failed: false } as const;
    }
  }
  if (page.url() !== baseline.url && config.draft.urlPatterns?.length && matchesAny(page.url(), config.draft.urlPatterns)) {
    return { confirmed: true, failed: false } as const;
  }
  return { confirmed: false, failed: false } as const;
}

async function verifyDraftPersistence(page: Page, config: BrowserPublisherConfig, expectedTitle: string) {
  const beforeReloadUrl = page.url();
  if (!isSafeStatusUrl(beforeReloadUrl, config)) return false;
  const reloaded = await page.reload({ waitUntil: "domcontentloaded", timeout: 60_000 })
    .then(() => true)
    .catch(() => false);
  if (!reloaded) return false;
  await page.waitForTimeout(1_000);
  if (await looksLoggedOut(page, config)) return false;
  if (!isSafeStatusUrl(page.url(), config)) return false;
  return locatorHasExactTitle(
    page,
    [...config.titleSelectors, ...(config.statusTitleSelectors || [])],
    expectedTitle,
  );
}

function safeCurrentUrl(page: Page, config: BrowserPublisherConfig) {
  const current = page.url();
  return isSafeStatusUrl(current, config) ? current : undefined;
}

function actionRequired(platformKey: string, code: BrowserSafeErrorCode, managementUrl?: string): PublicationResult {
  return {
    success: false,
    platformKey,
    status: "action_required",
    safeErrorCode: code,
    ...(managementUrl ? { managementUrl } : {}),
  };
}

export class BrowserFormPublisher implements PlatformPublisher {
  readonly platformKey: string;
  readonly verifiedCapabilities = ["auth"] as const;

  constructor(protected readonly config: BrowserPublisherConfig) {
    const issues = validateBrowserPublisherConfig(config);
    if (issues.length) throw new Error(`invalid_browser_publisher_config:${config.platformKey}:${issues.join(",")}`);
    this.platformKey = config.platformKey;
  }

  private enabled() {
    return enabledPlatformKeys().has(this.platformKey);
  }

  async checkAuth(credentials: PlatformCredentials) {
    if (!hasAuthCookie(credentials, this.config)) return { ok: false };
    const { browser, context } = await createPublisherBrowserContext(credentials);
    try {
      const page = await context.newPage();
      await page.goto(this.config.editorUrl, { waitUntil: "domcontentloaded", timeout: 45_000 });
      await page.waitForTimeout(1_000);
      if (await looksLoggedOut(page, this.config)) return { ok: false };
      const title = await firstVisible(page, this.config.titleSelectors, 2_000);
      const content = await firstVisible(page, this.config.contentSelectors, 2_000);
      return { ok: Boolean(title && content) };
    } catch {
      return { ok: false };
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    if (!this.enabled()) return { platformKey: this.platformKey, status: "unknown" };
    if (!hasAuthCookie(input.credentials, this.config)) {
      return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    if (!input.managementUrl || !isSafeStatusUrl(input.managementUrl, this.config)) {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "unsafe_status_url" };
    }
    if (!input.externalPostId?.trim() && !input.expectedTitle?.trim()) {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "status_target_unbound" };
    }

    const { browser, context } = await createPublisherBrowserContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto(input.managementUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1000);
      if (await looksLoggedOut(page, this.config)) {
        return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }
      const statusScope = await statusScopeForInput(page, this.config, input);
      const managementUrl = safeCurrentUrl(page, this.config);
      if (!statusScope) {
        return { platformKey: this.platformKey, status: "unknown", managementUrl, safeErrorCode: "status_target_unbound" };
      }
      const publicUrl = await detectPublicUrl(page, this.config, {
        allowLinks: true,
        externalPostId: input.externalPostId,
        scope: statusScope,
      });
      if (publicUrl) {
        return { platformKey: this.platformKey, status: "published", publicUrl, managementUrl };
      }
      if (await firstVisible(statusScope, DEFAULT_STATUS_FAILURE_SELECTORS, 500)) {
        return { platformKey: this.platformKey, status: "failed", managementUrl, safeErrorCode: "content_rejected" };
      }
      if (await firstVisible(statusScope, DEFAULT_STATUS_REVIEW_SELECTORS, 500)) {
        return { platformKey: this.platformKey, status: "submitted", managementUrl };
      }
      // “已发布”但没有文章 URL 时只保守标记为 submitted，绝不伪造公开链接。
      if (await firstVisible(statusScope, DEFAULT_STATUS_PUBLISHED_SELECTORS, 500)) {
        return { platformKey: this.platformKey, status: "submitted", managementUrl };
      }
      return { platformKey: this.platformKey, status: "unknown", managementUrl };
    } catch {
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "platform_unavailable" };
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    if (!this.enabled()) return actionRequired(this.platformKey, "platform_not_verified");
    if (!hasAuthCookie(input.credentials, this.config)) {
      return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }

    const { browser, context } = await createPublisherBrowserContext(input.credentials);
    try {
      const page = await context.newPage();
      await page.goto(this.config.editorUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForTimeout(1200);
      if (await looksLoggedOut(page, this.config)) {
        return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
      }

      const title = await firstVisible(page, this.config.titleSelectors);
      const content = await firstVisible(page, this.config.contentSelectors);
      const managementUrl = safeCurrentUrl(page, this.config);
      if (!title || !content) return actionRequired(this.platformKey, "editor_changed", managementUrl);

      await title.fill(input.title.slice(0, this.config.titleLimit || 200));
      const contentValue = input.contentText || input.contentHtml.replace(/<[^>]+>/g, " ");
      await content.fill(contentValue.slice(0, this.config.contentLimit || 200_000));

      if (this.config.tagStrategy?.phase !== "publish_dialog") {
        const tagsReady = await fillTags(page, input, this.config.tagStrategy);
        if (!tagsReady) return actionRequired(this.platformKey, "platform_fields_required", safeCurrentUrl(page, this.config));
      }

      const coverUploaded = await uploadCover(page, input, this.config).catch(() => false);
      if (this.config.coverRequired && !coverUploaded) {
        return actionRequired(this.platformKey, "media_invalid", safeCurrentUrl(page, this.config));
      }

      if (input.publishMode === "draft") {
        const baseline = await captureDraftBaseline(page, this.config);
        if (this.config.draft.actionSelectors?.length) {
          const save = await firstVisible(page, this.config.draft.actionSelectors);
          if (!save) return actionRequired(this.platformKey, "draft_control_changed", safeCurrentUrl(page, this.config));
          await save.click();
        }
        const draft = await confirmDraft(page, this.config, baseline);
        const editUrl = safeCurrentUrl(page, this.config);
        if (draft.failed) {
          return { success: false, platformKey: this.platformKey, status: "failed", managementUrl: editUrl, safeErrorCode: "content_rejected" };
        }
        // UI 提示只作为辅助证据；最终必须重载后精确读回本次标题。
        // 因此旧的“保存成功”提示既不能造成误判，也不会阻断已真实持久化的草稿。
        const persisted = await verifyDraftPersistence(page, this.config, input.title.slice(0, this.config.titleLimit || 200));
        const persistedUrl = safeCurrentUrl(page, this.config) || editUrl;
        if (!persisted) return actionRequired(this.platformKey, "draft_save_unconfirmed", persistedUrl);
        return { success: true, platformKey: this.platformKey, status: "drafted", editUrl: persistedUrl, managementUrl: persistedUrl };
      }

      const baselineBody = await pageText(page);
      const baselinePublicUrl = await detectPublicUrl(page, this.config, {
        expectedTitle: input.title.slice(0, this.config.titleLimit || 200),
      });
      for (let index = 0; index < this.config.publishSteps.length; index += 1) {
        const step = this.config.publishSteps[index];
        const control = await firstVisible(page, step.selectors);
        if (!control) {
          if (step.optional) continue;
          return actionRequired(this.platformKey, "publish_control_changed", safeCurrentUrl(page, this.config));
        }
        await control.click();
        await page.waitForTimeout(boundedWait(step.waitAfterMs, 800));
        if (index === 0 && this.config.tagStrategy?.phase === "publish_dialog") {
          const tagsReady = await fillTags(page, input, this.config.tagStrategy);
          if (!tagsReady) return actionRequired(this.platformKey, "platform_fields_required", safeCurrentUrl(page, this.config));
        }
      }

      const evidence = await waitForPublicationEvidence(
        page,
        this.config,
        baselineBody,
        baselinePublicUrl,
        input.title.slice(0, this.config.titleLimit || 200),
      );
      const resultManagementUrl = safeCurrentUrl(page, this.config);
      if (evidence.kind === "failed") {
        return { success: false, platformKey: this.platformKey, status: "failed", managementUrl: resultManagementUrl, safeErrorCode: "content_rejected" };
      }
      if (evidence.kind === "action_required") {
        return actionRequired(this.platformKey, evidence.safeErrorCode || "platform_fields_required", resultManagementUrl);
      }
      if (evidence.kind === "published" && evidence.publicUrl) {
        return { success: true, platformKey: this.platformKey, status: "published", publicUrl: evidence.publicUrl, managementUrl: resultManagementUrl };
      }
      if (evidence.kind === "submitted") {
        return { success: true, platformKey: this.platformKey, status: "submitted", managementUrl: resultManagementUrl };
      }
      return actionRequired(this.platformKey, "publish_result_unconfirmed", resultManagementUrl);
    } catch (error) {
      const message = error instanceof Error ? error.message : "";
      const code: BrowserSafeErrorCode = message === "media_invalid" ? "media_invalid" : "platform_unavailable";
      return actionRequired(this.platformKey, code);
    } finally {
      await context.close().catch(() => undefined);
      await browser.close().catch(() => undefined);
    }
  }
}
