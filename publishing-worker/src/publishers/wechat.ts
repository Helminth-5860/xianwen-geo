import type {
  PlatformCredentials,
  PlatformPublisher,
  PublicationInput,
  PublicationResult,
  PublicationStatusInput,
  PublicationStatusResult,
} from "./types.js";

type WechatResponse = Record<string, unknown> & { errcode?: number; errmsg?: string };

async function jsonRequest(url: string, init?: RequestInit): Promise<WechatResponse> {
  const response = await fetch(url, init);
  if (!response.ok) throw new Error("platform_unavailable");
  const data = (await response.json()) as WechatResponse;
  if (typeof data.errcode === "number" && data.errcode !== 0) {
    const authCodes = new Set([40001, 40014, 42001]);
    throw new Error(authCodes.has(data.errcode) ? "authorization_required" : "platform_rejected_request");
  }
  return data;
}

async function accessToken(credentials: PlatformCredentials) {
  if (credentials.access_token) return credentials.access_token;
  if (!credentials.app_id || !credentials.app_secret) throw new Error("authorization_required");
  const data = await jsonRequest(
    `https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid=${encodeURIComponent(credentials.app_id)}&secret=${encodeURIComponent(credentials.app_secret)}`,
  );
  const token = typeof data.access_token === "string" ? data.access_token : "";
  if (!token) throw new Error("authorization_required");
  return token;
}

async function fetchImage(url: string) {
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error("media_download_failed");
  const bytes = await response.arrayBuffer();
  if (!bytes.byteLength || bytes.byteLength > 10 * 1024 * 1024) throw new Error("media_invalid");
  return { bytes, type: response.headers.get("content-type") || "image/jpeg" };
}

async function uploadMaterial(token: string, url: string, type: "thumb" | "image") {
  const image = await fetchImage(url);
  const form = new FormData();
  form.append("media", new Blob([image.bytes], { type: image.type }), type === "thumb" ? "cover.jpg" : "image.jpg");
  const endpoint = type === "thumb"
    ? `https://api.weixin.qq.com/cgi-bin/material/add_material?access_token=${encodeURIComponent(token)}&type=thumb`
    : `https://api.weixin.qq.com/cgi-bin/media/uploadimg?access_token=${encodeURIComponent(token)}`;
  const response = await fetch(endpoint, { method: "POST", body: form });
  if (!response.ok) throw new Error("platform_unavailable");
  const data = (await response.json()) as WechatResponse;
  if (typeof data.errcode === "number" && data.errcode !== 0) throw new Error("media_invalid");
  return data;
}

async function getPublishStatus(token: string, publishId: string) {
  return jsonRequest(
    `https://api.weixin.qq.com/cgi-bin/freepublish/get?access_token=${encodeURIComponent(token)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ publish_id: publishId }),
    },
  );
}

function publicArticleUrl(status: WechatResponse) {
  const detail = status.article_detail as { item?: Array<{ article_url?: string }> } | undefined;
  return detail?.item?.find((item) => typeof item.article_url === "string")?.article_url;
}

export class WechatPublisher implements PlatformPublisher {
  readonly platformKey = "wechat";
  // 正式 API 流程已接入，但必须用显问测试公众号完成真实发布验收后才能标记为已验证。
  readonly verifiedCapabilities = [] as const;

  async checkAuth(credentials: PlatformCredentials) {
    try {
      await accessToken(credentials);
      return { ok: true };
    } catch {
      return { ok: false };
    }
  }

  async checkStatus(input: PublicationStatusInput): Promise<PublicationStatusResult> {
    if (!input.externalPostId) {
      return { platformKey: this.platformKey, status: "unknown" };
    }
    try {
      const token = await accessToken(input.credentials);
      const status = await getPublishStatus(token, input.externalPostId);
      const publishStatus = typeof status.publish_status === "number" ? status.publish_status : -1;
      if (publishStatus === 0) {
        const publicUrl = publicArticleUrl(status);
        return publicUrl
          ? { platformKey: this.platformKey, status: "published", publicUrl }
          : { platformKey: this.platformKey, status: "submitted" };
      }
      if ([2, 3, 5, 6].includes(publishStatus)) {
        return { platformKey: this.platformKey, status: "failed", safeErrorCode: "content_rejected" };
      }
      return { platformKey: this.platformKey, status: "submitted" };
    } catch (error) {
      const code = error instanceof Error ? error.message : "platform_unavailable";
      if (code === "authorization_required") {
        return { platformKey: this.platformKey, status: "auth_required", safeErrorCode: code };
      }
      return { platformKey: this.platformKey, status: "unknown", safeErrorCode: "platform_unavailable" };
    }
  }

  async publish(input: PublicationInput): Promise<PublicationResult> {
    try {
      const token = await accessToken(input.credentials);
      const cover = input.assets.find((item) => item.role === "cover") || input.assets[0];
      if (!cover) {
        return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "media_invalid" };
      }
      const coverResult = await uploadMaterial(token, cover.url, "thumb");
      const thumbMediaId = typeof coverResult.media_id === "string" ? coverResult.media_id : "";
      if (!thumbMediaId) return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "media_invalid" };

      let content = input.contentHtml;
      for (const asset of input.assets.filter((item) => item.role !== "cover").slice(0, 8)) {
        try {
          const uploaded = await uploadMaterial(token, asset.url, "image");
          const url = typeof uploaded.url === "string" ? uploaded.url : "";
          if (url) content += `<p><img src="${url}" alt="${(asset.alt || "").replace(/[<>\"]/g, "")}" /></p>`;
        } catch {
          // 单张正文插图失败不应破坏主文章；封面失败才阻断发布。
        }
      }

      const draft = await jsonRequest(
        `https://api.weixin.qq.com/cgi-bin/draft/add?access_token=${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            articles: [
              {
                title: input.title.slice(0, 64),
                author: "",
                digest: (input.summary || input.contentText).slice(0, 120),
                content,
                content_source_url: "",
                thumb_media_id: thumbMediaId,
                need_open_comment: 0,
                only_fans_can_comment: 0,
              },
            ],
          }),
        },
      );
      const mediaId = typeof draft.media_id === "string" ? draft.media_id : "";
      if (!mediaId) return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_unavailable" };
      if (input.publishMode === "draft") {
        return { success: true, platformKey: this.platformKey, status: "drafted", externalPostId: mediaId };
      }

      const submitted = await jsonRequest(
        `https://api.weixin.qq.com/cgi-bin/freepublish/submit?access_token=${encodeURIComponent(token)}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ media_id: mediaId }),
        },
      );
      const publishId = typeof submitted.publish_id === "string" ? submitted.publish_id : "";
      if (!publishId) return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: "platform_unavailable" };

      for (let attempt = 0; attempt < 4; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 1800));
        const status = await getPublishStatus(token, publishId);
        const publishStatus = typeof status.publish_status === "number" ? status.publish_status : -1;
        if (publishStatus === 0) {
          const publicUrl = publicArticleUrl(status);
          if (publicUrl) {
            return { success: true, platformKey: this.platformKey, status: "published", externalPostId: publishId, publicUrl };
          }
          return { success: true, platformKey: this.platformKey, status: "submitted", externalPostId: publishId };
        }
        if ([2, 3, 5, 6].includes(publishStatus)) {
          return { success: false, platformKey: this.platformKey, status: "failed", externalPostId: publishId, safeErrorCode: "content_rejected" };
        }
      }
      return { success: true, platformKey: this.platformKey, status: "submitted", externalPostId: publishId };
    } catch (error) {
      const code = error instanceof Error ? error.message : "platform_unavailable";
      if (code === "authorization_required") return { success: false, platformKey: this.platformKey, status: "auth_required", safeErrorCode: code };
      return { success: false, platformKey: this.platformKey, status: "failed", safeErrorCode: code === "media_invalid" ? "media_invalid" : "platform_unavailable" };
    }
  }
}
