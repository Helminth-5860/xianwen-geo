import crypto from "node:crypto";
import http, { type IncomingMessage, type ServerResponse } from "node:http";
import { URL } from "node:url";

import {
  deleteAuthSession,
  getAuthSession,
  internalSessionPayload,
  sessionClick,
  sessionPreview,
  startAuthSession,
  viewerAuthorized,
} from "./auth-sessions.js";
import { getPublisher, publisherCapabilities } from "./publishers/index.js";
import type { PlatformCredentials, PublicationInput } from "./publishers/types.js";

const port = Number(process.env.PORT || "8092");
const host = process.env.HOST || "0.0.0.0";
const publicBaseUrl = (process.env.PUBLISHING_WORKER_PUBLIC_BASE_URL || `http://localhost:${port}`).replace(/\/$/, "");
const internalSecret = process.env.PUBLISHING_WORKER_INTERNAL_SECRET || "";

if (internalSecret.length < 32) {
  throw new Error("PUBLISHING_WORKER_INTERNAL_SECRET must be at least 32 characters");
}

const json = (response: ServerResponse, status: number, payload: unknown) => {
  response.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  });
  response.end(JSON.stringify(payload));
};

const text = (response: ServerResponse, status: number, body: string, contentType = "text/plain; charset=utf-8") => {
  response.writeHead(status, {
    "Content-Type": contentType,
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; img-src 'self' data:; style-src 'unsafe-inline'; script-src 'unsafe-inline'; frame-ancestors 'none'",
  });
  response.end(body);
};

const safeSecretEqual = (provided: string) => {
  const left = Buffer.from(internalSecret);
  const right = Buffer.from(provided);
  return left.length === right.length && crypto.timingSafeEqual(left, right);
};

const internalAuthorized = (request: IncomingMessage) => {
  const header = request.headers.authorization || "";
  if (!header.startsWith("Bearer ")) return false;
  return safeSecretEqual(header.slice("Bearer ".length));
};

async function readJson(request: IncomingMessage, maxBytes = 64 * 1024): Promise<Record<string, unknown>> {
  const chunks: Buffer[] = [];
  let total = 0;
  for await (const chunk of request) {
    const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk);
    total += buffer.length;
    if (total > maxBytes) throw new Error("request_too_large");
    chunks.push(buffer);
  }
  if (!chunks.length) return {};
  const parsed = JSON.parse(Buffer.concat(chunks).toString("utf8"));
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("invalid_json");
  return parsed as Record<string, unknown>;
}

const escapeHtml = (value: string) =>
  value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");

function authorizationPage(sessionId: string, token: string, platformName: string) {
  const safeId = encodeURIComponent(sessionId);
  const safeToken = encodeURIComponent(token);
  return `<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>授权${escapeHtml(platformName)}</title>
<style>
body{margin:0;background:#f4f6f9;color:#111827;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC",sans-serif}
main{max-width:1080px;margin:0 auto;padding:24px}
.card{background:#fff;border:1px solid #e5e7eb;border-radius:18px;padding:22px;box-shadow:0 14px 34px rgba(15,23,42,.07)}
h1{font-size:22px;margin:0 0 8px}.hint{color:#667085;line-height:1.7;margin-bottom:18px}
.preview{width:100%;min-height:560px;object-fit:contain;background:#fff;border:1px solid #e5e7eb;border-radius:12px;cursor:pointer}
.status{display:inline-flex;margin:0 0 16px;padding:6px 10px;border-radius:999px;background:#eef4ff;color:#344054;font-size:14px}
.safe{margin-top:16px;color:#667085;font-size:13px;line-height:1.7}
</style>
</head>
<body><main><div class="card">
<h1>授权${escapeHtml(platformName)}</h1>
<p class="hint">请优先使用扫码完成登录。若平台当前显示其他登录方式，可点击下方画面切换“扫码登录”或刷新二维码。显问不会提供键盘输入，因此平台密码和短信验证码不会经过这个页面。</p>
<div id="status" class="status">正在等待完成登录</div>
<img id="preview" class="preview" alt="平台授权页面" src="/authorize/${safeId}/preview?token=${safeToken}&v=0" />
<p class="safe">此授权画面只对当前一次性链接开放，并会在授权结束后失效。请勿把此页面转发给其他人。</p>
</div></main>
<script>
const statusEl=document.getElementById('status');
const preview=document.getElementById('preview');
let tick=0;
let finished=false;
preview.addEventListener('click',async(event)=>{
  if(finished)return;
  const rect=preview.getBoundingClientRect();
  const naturalW=preview.naturalWidth||1280;
  const naturalH=preview.naturalHeight||900;
  const renderedRatio=rect.width/rect.height;
  const naturalRatio=naturalW/naturalH;
  let contentW=rect.width,contentH=rect.height,offsetX=0,offsetY=0;
  if(renderedRatio>naturalRatio){contentW=rect.height*naturalRatio;offsetX=(rect.width-contentW)/2;}
  else{contentH=rect.width/naturalRatio;offsetY=(rect.height-contentH)/2;}
  const px=event.clientX-rect.left-offsetX;
  const py=event.clientY-rect.top-offsetY;
  if(px<0||py<0||px>contentW||py>contentH)return;
  const x=Math.max(0,Math.min(1280,px/contentW*1280));
  const y=Math.max(0,Math.min(900,py/contentH*900));
  try{
    await fetch('/authorize/${safeId}/click?token=${safeToken}',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({x,y})});
    tick+=1;preview.src='/authorize/${safeId}/preview?token=${safeToken}&v='+tick;
  }catch{}
});
async function refresh(){
  try{
    const response=await fetch('/authorize/${safeId}/status?token=${safeToken}',{cache:'no-store'});
    const data=await response.json();
    if(data.status==='succeeded'){finished=true;statusEl.textContent='授权成功，可以关闭此窗口';preview.style.opacity='.45';return;}
    if(data.status==='expired'){finished=true;statusEl.textContent='授权已过期，请返回显问重新授权';return;}
    if(data.status==='failed'){finished=true;statusEl.textContent='本次授权未完成，请返回显问重新尝试';return;}
    statusEl.textContent='正在等待完成登录';
    tick+=1;preview.src='/authorize/${safeId}/preview?token=${safeToken}&v='+tick;
    setTimeout(refresh,1800);
  }catch{statusEl.textContent='授权页面正在重新连接';setTimeout(refresh,2500);}
}
setTimeout(refresh,1600);
</script></body></html>`;
}

function validatePublishInput(body: Record<string, unknown>): PublicationInput | null {
  const platformKey = typeof body.platform_key === "string" ? body.platform_key : "";
  const targetId = typeof body.target_id === "string" ? body.target_id : "";
  const title = typeof body.title === "string" ? body.title.trim() : "";
  const contentHtml = typeof body.content_html === "string" ? body.content_html : "";
  const contentText = typeof body.content_text === "string" ? body.content_text : "";
  const publishMode = body.publish_mode === "draft" ? "draft" : body.publish_mode === "public" ? "public" : null;
  const credentials = body.credentials;
  if (!platformKey || !targetId || !title || !publishMode || !credentials || typeof credentials !== "object" || Array.isArray(credentials)) return null;
  const tags = Array.isArray(body.tags) ? body.tags.filter((item): item is string => typeof item === "string").slice(0, 30) : [];
  const assets = Array.isArray(body.assets)
    ? body.assets
        .filter((item): item is { role: "cover" | "inline" | "information"; url: string; alt?: string } => {
          if (!item || typeof item !== "object" || Array.isArray(item)) return false;
          const candidate = item as Record<string, unknown>;
          return ["cover", "inline", "information"].includes(String(candidate.role)) && typeof candidate.url === "string";
        })
        .slice(0, 20)
    : [];
  return {
    targetId,
    title: title.slice(0, 500),
    contentHtml,
    contentText,
    summary: typeof body.summary === "string" ? body.summary.slice(0, 1000) : undefined,
    tags,
    assets,
    credentials: credentials as PlatformCredentials,
    publishMode,
  };
}

const server = http.createServer(async (request, response) => {
  const method = request.method || "GET";
  const url = new URL(request.url || "/", publicBaseUrl);

  if (method === "GET" && url.pathname === "/health") {
    return json(response, 200, { status: "ok" });
  }

  if (method === "GET" && url.pathname === "/v1/capabilities") {
    if (!internalAuthorized(request)) return json(response, 401, { error: "unauthorized" });
    return json(response, 200, { publishers: publisherCapabilities() });
  }

  if (method === "POST" && url.pathname === "/v1/publish") {
    if (!internalAuthorized(request)) return json(response, 401, { error: "unauthorized" });
    try {
      const body = await readJson(request, 2 * 1024 * 1024);
      const platformKey = typeof body.platform_key === "string" ? body.platform_key : "";
      const publisher = getPublisher(platformKey);
      if (!publisher) return json(response, 409, { error: "platform_not_ready" });
      const input = validatePublishInput(body);
      if (!input) return json(response, 400, { error: "invalid_request" });
      const result = await publisher.publish(input);
      return json(response, 200, result);
    } catch (error) {
      const code = error instanceof Error ? error.message : "publish_failed";
      return json(response, code === "request_too_large" ? 413 : 500, { error: code });
    }
  }

  if (url.pathname === "/v1/auth-sessions" && method === "POST") {
    if (!internalAuthorized(request)) return json(response, 401, { error: "unauthorized" });
    try {
      const body = await readJson(request);
      const id = typeof body.id === "string" ? body.id : "";
      const platformKey = typeof body.platform_key === "string" ? body.platform_key : "";
      const expiresAt = typeof body.expires_at === "string" ? Date.parse(body.expires_at) : NaN;
      if (!id || !platformKey || !Number.isFinite(expiresAt)) return json(response, 400, { error: "invalid_request" });
      const result = await startAuthSession({ id, platformKey, expiresAt, publicBaseUrl });
      return json(response, 201, {
        remote_session_ref: result.remoteSessionRef,
        action_url: result.actionUrl,
        status: result.status,
      });
    } catch (error) {
      const code = error instanceof Error ? error.message : "start_failed";
      const status = code === "platform_not_ready" ? 409 : 500;
      return json(response, status, { error: code });
    }
  }

  const internalMatch = url.pathname.match(/^\/v1\/auth-sessions\/([^/]+)$/);
  if (internalMatch) {
    if (!internalAuthorized(request)) return json(response, 401, { error: "unauthorized" });
    const id = decodeURIComponent(internalMatch[1]);
    if (method === "GET") {
      const session = getAuthSession(id);
      return session ? json(response, 200, internalSessionPayload(session)) : json(response, 404, { error: "not_found" });
    }
    if (method === "DELETE") {
      await deleteAuthSession(id);
      response.writeHead(204, { "Cache-Control": "no-store" });
      return response.end();
    }
  }

  const pageMatch = url.pathname.match(/^\/authorize\/([^/]+)$/);
  if (method === "GET" && pageMatch) {
    const id = decodeURIComponent(pageMatch[1]);
    const token = url.searchParams.get("token") || "";
    const session = getAuthSession(id);
    if (!session || !viewerAuthorized(session, token)) return text(response, 404, "授权链接已失效");
    return text(response, 200, authorizationPage(id, token, session.platform.name), "text/html; charset=utf-8");
  }

  const statusMatch = url.pathname.match(/^\/authorize\/([^/]+)\/status$/);
  if (method === "GET" && statusMatch) {
    const id = decodeURIComponent(statusMatch[1]);
    const token = url.searchParams.get("token") || "";
    const session = getAuthSession(id);
    if (!session || !viewerAuthorized(session, token)) return json(response, 404, { error: "not_found" });
    return json(response, 200, { status: session.status });
  }

  const clickMatch = url.pathname.match(/^\/authorize\/([^/]+)\/click$/);
  if (method === "POST" && clickMatch) {
    const id = decodeURIComponent(clickMatch[1]);
    const token = url.searchParams.get("token") || "";
    const session = getAuthSession(id);
    if (!session || !viewerAuthorized(session, token)) return json(response, 404, { error: "not_found" });
    try {
      const body = await readJson(request, 2048);
      const x = typeof body.x === "number" ? body.x : NaN;
      const y = typeof body.y === "number" ? body.y : NaN;
      await sessionClick(session, x, y);
      return json(response, 200, { clicked: true });
    } catch {
      return json(response, 400, { error: "invalid_click" });
    }
  }

  const previewMatch = url.pathname.match(/^\/authorize\/([^/]+)\/preview$/);
  if (method === "GET" && previewMatch) {
    const id = decodeURIComponent(previewMatch[1]);
    const token = url.searchParams.get("token") || "";
    const session = getAuthSession(id);
    if (!session || !viewerAuthorized(session, token)) return text(response, 404, "授权链接已失效");
    const image = await sessionPreview(session);
    if (!image) return text(response, 409, "授权画面暂不可用");
    response.writeHead(200, {
      "Content-Type": "image/png",
      "Cache-Control": "no-store, max-age=0",
      "X-Content-Type-Options": "nosniff",
      "Content-Security-Policy": "default-src 'none'",
    });
    return response.end(image);
  }

  return json(response, 404, { error: "not_found" });
});

server.listen(port, host, () => {
  console.log(`xianwen publishing worker listening on ${host}:${port}`);
});

const shutdown = async () => {
  server.close(() => process.exit(0));
  setTimeout(() => process.exit(1), 5000).unref();
};

process.on("SIGTERM", () => void shutdown());
process.on("SIGINT", () => void shutdown());
