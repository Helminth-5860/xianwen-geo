import { chromium } from "playwright";

import type { PlatformCredentials } from "./types.js";

const headless = (process.env.PUBLISHING_WORKER_BROWSER_HEADLESS || "true").toLowerCase() !== "false";

function storageState(credentials: PlatformCredentials) {
  return {
    cookies: (credentials.cookies || [])
      .filter((item) => item.name && item.domain)
      .map((item) => ({
        name: item.name,
        value: item.value,
        domain: item.domain,
        path: item.path || "/",
        expires: typeof item.expires === "number" ? item.expires : -1,
        httpOnly: Boolean(item.httpOnly),
        secure: Boolean(item.secure),
        sameSite: item.sameSite || ("Lax" as const),
      })),
    origins: (credentials.origins || []).map((item) => ({
      origin: item.origin,
      localStorage: item.localStorage.map((entry) => ({ name: entry.name, value: entry.value })),
    })),
  };
}

export async function createPublisherBrowserContext(
  credentials: PlatformCredentials,
  viewport = { width: 1360, height: 900 },
) {
  const browser = await chromium.launch({
    headless,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
  });
  try {
    const context = await browser.newContext({
      viewport,
      locale: "zh-CN",
      storageState: storageState(credentials),
    });
    return { browser, context };
  } catch (error) {
    await browser.close().catch(() => undefined);
    throw error;
  }
}
