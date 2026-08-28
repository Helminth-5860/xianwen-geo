import crypto from "node:crypto";
import { chromium, type Browser, type BrowserContext, type Page } from "playwright";

import { LOGIN_PLATFORMS, type LoginPlatform } from "./platforms.js";

export type AuthSessionStatus =
  | "starting"
  | "waiting_user"
  | "succeeded"
  | "failed"
  | "expired";

export type AuthCredentialPayload = Readonly<{
  cookies: Array<{
    name: string;
    value: string;
    domain: string;
    path: string;
    expires: number;
    httpOnly: boolean;
    secure: boolean;
    sameSite: "Strict" | "Lax" | "None";
  }>;
}>;

export type ManagedAuthSession = {
  id: string;
  platform: LoginPlatform;
  viewerTokenDigest: string;
  status: AuthSessionStatus;
  expiresAt: number;
  browser: Browser;
  context: BrowserContext;
  page: Page;
  credentials: AuthCredentialPayload | null;
  errorCode: string;
  monitor: NodeJS.Timeout | null;
  cleanup: NodeJS.Timeout | null;
};

const sessions = new Map<string, ManagedAuthSession>();

const sha256 = (value: string) => crypto.createHash("sha256").update(value).digest("hex");

const safeEqualDigest = (expected: string, actual: string) => {
  const left = Buffer.from(expected, "hex");
  const right = Buffer.from(actual, "hex");
  return left.length === right.length && crypto.timingSafeEqual(left, right);
};

async function closeSessionResources(session: ManagedAuthSession) {
  if (session.monitor) clearInterval(session.monitor);
  session.monitor = null;
  try {
    await session.context.close();
  } catch {
    // Context may already be closed after a browser failure.
  }
  try {
    await session.browser.close();
  } catch {
    // Browser may already be closed after a browser failure.
  }
}

function scheduleCleanup(session: ManagedAuthSession, delayMs: number) {
  if (session.cleanup) clearTimeout(session.cleanup);
  session.cleanup = setTimeout(() => {
    sessions.delete(session.id);
    session.credentials = null;
    void closeSessionResources(session);
  }, Math.max(5_000, delayMs));
  session.cleanup.unref();
}

async function captureCredentials(session: ManagedAuthSession) {
  const allCookies = await session.context.cookies();
  const allowedDomains = new Set(
    [new URL(session.platform.loginUrl).hostname, ...session.platform.cookieDomains].map((value) =>
      value.replace(/^\./, ""),
    ),
  );
  const cookies = allCookies.filter((cookie) => {
    const domain = cookie.domain.replace(/^\./, "");
    return [...allowedDomains].some(
      (allowed) => domain === allowed || domain.endsWith(`.${allowed}`) || allowed.endsWith(`.${domain}`),
    );
  });
  session.credentials = {
    cookies: cookies.map((cookie) => ({
      name: cookie.name,
      value: cookie.value,
      domain: cookie.domain,
      path: cookie.path,
      expires: cookie.expires,
      httpOnly: cookie.httpOnly,
      secure: cookie.secure,
      sameSite: cookie.sameSite,
    })),
  };
  session.status = "succeeded";
  await closeSessionResources(session);
  // Django polls every ~2 seconds. Keep a short grace period for retrieval, then
  // erase captured platform credentials even if the customer closes the UI early.
  scheduleCleanup(session, 120_000);
}

async function monitorSession(session: ManagedAuthSession) {
  if (Date.now() >= session.expiresAt) {
    session.status = "expired";
    session.errorCode = "authorization_timeout";
    await closeSessionResources(session);
    scheduleCleanup(session, 60_000);
    return;
  }
  try {
    const cookies = await session.context.cookies();
    const success = cookies.some(
      (cookie) => session.platform.successCookies.includes(cookie.name) && Boolean(cookie.value),
    );
    if (success) {
      await captureCredentials(session);
    }
  } catch {
    session.status = "failed";
    session.errorCode = "platform_unavailable";
    await closeSessionResources(session);
    scheduleCleanup(session, 60_000);
  }
}

export async function startAuthSession(input: {
  id: string;
  platformKey: string;
  expiresAt: number;
  publicBaseUrl: string;
}) {
  if (sessions.has(input.id)) throw new Error("session_exists");
  const platform = LOGIN_PLATFORMS[input.platformKey];
  if (!platform) throw new Error("platform_not_ready");
  if (input.expiresAt <= Date.now()) throw new Error("session_expired");

  const viewerToken = crypto.randomBytes(32).toString("base64url");
  const browser = await chromium.launch({
    headless: true,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
  });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 900 },
    locale: "zh-CN",
  });
  const page = await context.newPage();
  const session: ManagedAuthSession = {
    id: input.id,
    platform,
    viewerTokenDigest: sha256(viewerToken),
    status: "starting",
    expiresAt: input.expiresAt,
    browser,
    context,
    page,
    credentials: null,
    errorCode: "",
    monitor: null,
    cleanup: null,
  };
  sessions.set(input.id, session);

  // Absolute TTL cleanup is a second line of defense if neither the UI nor Django
  // calls DELETE after a failed/abandoned authorization attempt.
  scheduleCleanup(session, Math.max(30_000, input.expiresAt - Date.now() + 60_000));

  try {
    await page.goto(platform.loginUrl, { waitUntil: "domcontentloaded", timeout: 60_000 });
    session.status = "waiting_user";
    session.monitor = setInterval(() => void monitorSession(session), 1500);
  } catch {
    session.status = "failed";
    session.errorCode = "platform_unavailable";
    await closeSessionResources(session);
    scheduleCleanup(session, 60_000);
  }

  const base = input.publicBaseUrl.replace(/\/$/, "");
  return {
    remoteSessionRef: input.id,
    // Fragment values are not sent in HTTP requests or reverse-proxy access logs.
    // The browser exchanges it once for an HttpOnly SameSite cookie.
    actionUrl: `${base}/authorize/${encodeURIComponent(input.id)}#token=${encodeURIComponent(viewerToken)}`,
    status: session.status,
  };
}

export function getAuthSession(id: string) {
  return sessions.get(id) ?? null;
}

export function viewerAuthorized(session: ManagedAuthSession, token: string) {
  if (!token) return false;
  return safeEqualDigest(session.viewerTokenDigest, sha256(token));
}

export async function sessionPreview(session: ManagedAuthSession) {
  if (session.status === "expired" || session.status === "failed") return null;
  if (session.status === "succeeded") return null;
  try {
    return await session.page.screenshot({ type: "png", fullPage: false });
  } catch {
    return null;
  }
}

export async function sessionClick(session: ManagedAuthSession, x: number, y: number) {
  if (session.status !== "waiting_user") throw new Error("session_not_interactive");
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || x > 1280 || y < 0 || y > 900) {
    throw new Error("invalid_coordinates");
  }
  // 只代理鼠标点击，用于切换“扫码登录”、刷新二维码或确认非敏感提示。
  // 不提供键盘输入接口，因此平台密码、短信验证码等不会经过显问授权页。
  await session.page.mouse.click(Math.round(x), Math.round(y));
  await session.page.waitForTimeout(350);
}

export function internalSessionPayload(session: ManagedAuthSession) {
  return {
    id: session.id,
    platformKey: session.platform.key,
    status: session.status,
    errorCode: session.errorCode,
    credentials: session.status === "succeeded" ? session.credentials : null,
  };
}

export async function deleteAuthSession(id: string) {
  const session = sessions.get(id);
  if (!session) return;
  sessions.delete(id);
  if (session.cleanup) clearTimeout(session.cleanup);
  session.cleanup = null;
  session.credentials = null;
  await closeSessionResources(session);
}
