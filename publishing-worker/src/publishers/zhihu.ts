import type { PlatformCredentials, PlatformPublisher, PublicationInput, PublicationResult } from "./types.js";

const cookieHeader = (credentials: PlatformCredentials) =>
  (credentials.cookies || []).map((cookie) => `${cookie.name}=${cookie.value}`).join("; ");

const commonHeaders = (credentials: PlatformCredentials) => ({
  Cookie: cookieHeader(credentials),
  "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
  "X-Requested-With": "fetch",
});

const transformHtml = (html: string) =>
  html
    .replace(/<img([^>]+)src="([^"]+)"([^>]*)>/gi, '<figure><img$1src="$2"$3></figure>')
    .replace(/<pre><code class="language-(\w+)">/gi, '<pre lang="$1"><code>')
    .replace(/\s*data-(?!draft)[a-z-]+="[^"]*"/gi, "")
    .replace(/\s*style="[^"]*"/gi, "");

export class ZhihuPublisher implements PlatformPublisher {
  readonly platformKey = "zhihu";
  // 当前代码路径只把“授权检查 + 草稿创建”列为已验证目标；公开发布必须真实账号验收后再开放。
  readonly verifiedCapabilities = ["auth", "draft"] as const;

  async checkAuth(credentials: PlatformCredentials) {
    const cookie = cookieHeader(credentials);
    if (!cookie) return { ok: false };
    try {
      const response = await fetch("https://www.zhihu.com/api/v4/me", {
        headers: commonHeaders(credentials),
        signal: AbortSignal.timeout(15_000),
      });
      if (!response.ok) return { ok: false };
      const data = (await response.json()) as { id?: string; name?: string };
      return data.id
        ? { ok: true, displayName: data.name || "", externalAccountId: data.id }
        : { ok: false };
    } catch {
      return { ok: false };
    }
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    const auth = await this.checkAuth(input.credentials);
    if (!auth.ok) {
      return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: "authorization_required" };
    }
    if (input.publishMode === "public") {
      return {
        success: false,
        platformKey: this.platformKey,
        status: "action_required",
        safeErrorCode: "public_publish_not_verified",
      };
    }

    try {
      const createResponse = await fetch("https://zhuanlan.zhihu.com/api/articles/drafts", {
        method: "POST",
        headers: {
          ...commonHeaders(input.credentials),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: input.title, content: "", delta_time: 0 }),
        signal: AbortSignal.timeout(20_000),
      });
      if (!createResponse.ok) {
        return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_rejected" };
      }
      const created = (await createResponse.json()) as { id?: string | number };
      if (!created.id) {
        return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_invalid_response" };
      }
      const draftId = String(created.id);
      const updateResponse = await fetch(`https://zhuanlan.zhihu.com/api/articles/${draftId}/draft`, {
        method: "PATCH",
        headers: {
          ...commonHeaders(input.credentials),
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ title: input.title, content: transformHtml(input.contentHtml) }),
        signal: AbortSignal.timeout(20_000),
      });
      if (!updateResponse.ok) {
        return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_rejected" };
      }
      return {
        success: true,
        platformKey: this.platformKey,
        status: "drafted",
        externalPostId: draftId,
        editUrl: `https://zhuanlan.zhihu.com/p/${draftId}/edit`,
      };
    } catch {
      return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_unavailable" };
    }
  }
}
