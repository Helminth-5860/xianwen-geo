#!/usr/bin/env node

import { readFile, stat } from "node:fs/promises";
import path from "node:path";

import type {
  PlatformCredentials,
  PublicationAsset,
  PublicationInput,
  PublicationResult,
  PublicationStatusResult,
} from "../publishing-worker/src/publishers/types.js";

const PLATFORM_KEYS = [
  "wechat",
  "toutiao",
  "baijiahao",
  "zhihu",
  "xiaohongshu",
  "weibo",
  "bilibili",
  "douyin",
  "qq",
  "sohu",
  "csdn",
  "juejin",
  "cnblogs",
  "oschina",
  "segmentfault",
  "jianshu",
  "douban",
] as const;
type PlatformKey = (typeof PLATFORM_KEYS)[number];
const IMAGE_REQUIRED_PLATFORMS = new Set<PlatformKey>(["wechat", "xiaohongshu", "douyin"]);

type AcceptanceCase = Readonly<{
  id: string;
  platform: PlatformKey;
  sessionFile: string;
  publishMode: "draft" | "public";
  confirmPublic?: string;
  title: string;
  contentText: string;
  tags?: string[];
  assets: PublicationAsset[];
}>;

type Manifest = Readonly<{ cases: AcceptanceCase[] }>;

const REAL_SESSION_CONFIRMATION = "XIANWEN_REAL_TEST_SESSION";
const PUBLIC_CONFIRMATION = "XIANWEN_REAL_PUBLICATION";

function usage() {
  process.stdout.write(`
自动发文全平台真实账号批量验收（默认仅 dry-run）

用法：
  npx --prefix publishing-worker tsx scripts/accept-publishing-platforms.ts --manifest <绝对或相对路径>

执行草稿验收（会在真实平台显式保存草稿）：
  ... --execute --confirm-real-session ${REAL_SESSION_CONFIRMATION}

执行公开发布验收（会真实发布，三个确认缺一不可）：
  ... --execute --confirm-real-session ${REAL_SESSION_CONFIRMATION} \\
      --allow-public --confirm-public ${PUBLIC_CONFIRMATION}

批量并发数默认为 3，可用 --concurrency 1..4 调整。所有案例都会执行完毕后统一汇总，
单个平台失败不会中断其他平台；任何案例都不会自动重试发布动作。

公开发布还要求 manifest 中每个 public case 都包含：
  "confirmPublic": "${PUBLIC_CONFIRMATION}"

安全约束：
  - 未给 --execute 时只校验并显示脱敏计划，不启动浏览器、不读取会话内容、不上传图片。
  - 执行时必须逐 case 显式提供 sessionFile；工具不会打印 Cookie/localStorage。
  - 不会修改服务器开关，不会部署，不会重试发布；单项失败会记入汇总，不会中断其余平台。
  - status polling 只查询结果，不会再次点击发布。默认 1 次，可用 --status-polls 0..20 调整。
`);
}

function parseArguments(argv: string[]) {
  const flags = new Set<string>();
  const values = new Map<string, string>();
  const valueNames = new Set([
    "--manifest",
    "--confirm-real-session",
    "--confirm-public",
    "--status-polls",
    "--status-interval-ms",
    "--concurrency",
  ]);
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument.includes("=")) {
      const [name, ...rest] = argument.split("=");
      values.set(name, rest.join("="));
      continue;
    }
    if (valueNames.has(argument)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("--")) throw new Error(`missing_value:${argument}`);
      values.set(argument, value);
      index += 1;
      continue;
    }
    flags.add(argument);
  }
  return { flags, values };
}

function assertObject(value: unknown, label: string): asserts value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(`invalid_${label}`);
}

function validateAsset(value: unknown, caseId: string): PublicationAsset {
  assertObject(value, `asset_${caseId}`);
  const role = value.role;
  const url = value.url;
  if (!(["cover", "inline", "information"] as const).includes(role as PublicationAsset["role"])) {
    throw new Error(`invalid_asset_role:${caseId}`);
  }
  if (typeof url !== "string" || !/^https?:\/\//.test(url)) throw new Error(`invalid_asset_url:${caseId}`);
  return {
    role: role as PublicationAsset["role"],
    url,
    ...(typeof value.alt === "string" ? { alt: value.alt } : {}),
  };
}

function validateManifest(value: unknown): Manifest {
  assertObject(value, "manifest");
  if (!Array.isArray(value.cases) || value.cases.length === 0) throw new Error("manifest_cases_required");
  if (value.cases.length > 20) throw new Error("manifest_too_many_cases");
  const ids = new Set<string>();
  const cases = value.cases.map((candidate, index): AcceptanceCase => {
    assertObject(candidate, `case_${index}`);
    const id = typeof candidate.id === "string" ? candidate.id.trim() : "";
    if (!id || !/^[A-Za-z0-9_-]{1,80}$/.test(id) || ids.has(id)) throw new Error(`invalid_case_id:${index}`);
    ids.add(id);
    if (!PLATFORM_KEYS.includes(candidate.platform as PlatformKey)) {
      throw new Error(`invalid_platform:${id}`);
    }
    if (!(["draft", "public"] as const).includes(candidate.publishMode as "draft" | "public")) {
      throw new Error(`invalid_publish_mode:${id}`);
    }
    const sessionFile = typeof candidate.sessionFile === "string" ? candidate.sessionFile.trim() : "";
    const title = typeof candidate.title === "string" ? candidate.title.trim() : "";
    const contentText = typeof candidate.contentText === "string" ? candidate.contentText.trim() : "";
    if (!sessionFile) throw new Error(`session_file_required:${id}`);
    if (!title || !contentText) throw new Error(`content_required:${id}`);
    if (!Array.isArray(candidate.assets)) throw new Error(`assets_required:${id}`);
    if (IMAGE_REQUIRED_PLATFORMS.has(candidate.platform as PlatformKey) && candidate.assets.length === 0) {
      throw new Error(`assets_required:${id}`);
    }
    return {
      id,
      platform: candidate.platform as PlatformKey,
      sessionFile,
      publishMode: candidate.publishMode as "draft" | "public",
      ...(typeof candidate.confirmPublic === "string" ? { confirmPublic: candidate.confirmPublic } : {}),
      title,
      contentText,
      tags: Array.isArray(candidate.tags)
        ? candidate.tags.filter((tag): tag is string => typeof tag === "string").slice(0, 30)
        : [],
      assets: candidate.assets.slice(0, 20).map((asset) => validateAsset(asset, id)),
    };
  });
  return { cases };
}

function boundedInteger(value: string | undefined, fallback: number, minimum: number, maximum: number) {
  if (value === undefined) return fallback;
  const parsed = Number(value);
  if (!Number.isInteger(parsed) || parsed < minimum || parsed > maximum) throw new Error("invalid_numeric_option");
  return parsed;
}

function safeUrl(value: string | undefined) {
  if (!value) return undefined;
  try {
    const url = new URL(value);
    url.hash = "";
    url.search = "";
    return url.toString();
  } catch {
    return undefined;
  }
}

function safeResult(result: PublicationResult | PublicationStatusResult) {
  return {
    platformKey: result.platformKey,
    status: result.status,
    ...(Object.hasOwn(result, "success") ? { success: (result as PublicationResult).success } : {}),
    ...(Object.hasOwn(result, "externalPostId") && (result as PublicationResult).externalPostId
      ? { externalPostId: (result as PublicationResult).externalPostId }
      : {}),
    ...(result.publicUrl ? { publicUrl: safeUrl(result.publicUrl) } : {}),
    ...(result.managementUrl ? { managementUrl: safeUrl(result.managementUrl) } : {}),
    ...(Object.hasOwn(result, "editUrl") && (result as PublicationResult).editUrl
      ? { editUrl: safeUrl((result as PublicationResult).editUrl) }
      : {}),
    ...(result.safeErrorCode ? { safeErrorCode: result.safeErrorCode } : {}),
  };
}

async function loadCredentials(filename: string): Promise<PlatformCredentials> {
  const parsed: unknown = JSON.parse(await readFile(filename, "utf8"));
  assertObject(parsed, "session_file");
  const cookies = Array.isArray(parsed.cookies) ? parsed.cookies : [];
  const origins = Array.isArray(parsed.origins) ? parsed.origins : [];
  const accessToken = typeof parsed.access_token === "string" ? parsed.access_token : undefined;
  const refreshToken = typeof parsed.refresh_token === "string" ? parsed.refresh_token : undefined;
  const appId = typeof parsed.app_id === "string" ? parsed.app_id : undefined;
  const appSecret = typeof parsed.app_secret === "string" ? parsed.app_secret : undefined;
  if (cookies.length === 0 && origins.length === 0 && !accessToken && !(appId && appSecret)) {
    throw new Error("empty_real_session");
  }
  // The publisher browser-context performs the strict shape conversion. This tool
  // only passes the explicitly supplied storage-state object and never prints it.
  return {
    cookies,
    origins,
    ...(accessToken ? { access_token: accessToken } : {}),
    ...(refreshToken ? { refresh_token: refreshToken } : {}),
    ...(appId ? { app_id: appId } : {}),
    ...(appSecret ? { app_secret: appSecret } : {}),
  } as PlatformCredentials;
}

function redactedAsset(value: string) {
  try {
    const url = new URL(value);
    return `${url.protocol}//${url.host}${url.pathname}`;
  } catch {
    return "<invalid>";
  }
}

function simpleHtml(value: string) {
  return value
    .split(/\r?\n+/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => `<p>${line.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;")}</p>`)
    .join("");
}

async function main() {
  const { flags, values } = parseArguments(process.argv.slice(2));
  if (flags.has("--help") || flags.has("-h")) {
    usage();
    return;
  }

  const manifestArgument = values.get("--manifest");
  if (!manifestArgument) throw new Error("manifest_required");
  const manifestPath = path.resolve(manifestArgument);
  const manifest = validateManifest(JSON.parse(await readFile(manifestPath, "utf8")) as unknown);
  const manifestDirectory = path.dirname(manifestPath);
  const resolvedCases = manifest.cases.map((item) => ({
    ...item,
    sessionPath: path.resolve(manifestDirectory, item.sessionFile),
  }));

  const execute = flags.has("--execute");
  const allowPublic = flags.has("--allow-public");
  const publicCases = resolvedCases.filter((item) => item.publishMode === "public");
  if (execute && values.get("--confirm-real-session") !== REAL_SESSION_CONFIRMATION) {
    throw new Error("real_session_confirmation_required");
  }
  if (execute && publicCases.length) {
    if (!allowPublic || values.get("--confirm-public") !== PUBLIC_CONFIRMATION) {
      throw new Error("public_confirmation_required");
    }
    for (const item of publicCases) {
      if (item.confirmPublic !== PUBLIC_CONFIRMATION) throw new Error(`case_public_confirmation_required:${item.id}`);
    }
  }

  const plan = resolvedCases.map((item) => ({
    id: item.id,
    platform: item.platform,
    publishMode: item.publishMode,
    sessionFileProvided: true,
    titleCharacters: Array.from(item.title).length,
    assetCount: item.assets.length,
    assetLocations: item.assets.map((asset) => redactedAsset(asset.url)),
  }));
  process.stdout.write(`${JSON.stringify({ mode: execute ? "execute" : "dry-run", plan }, null, 2)}\n`);
  if (!execute) return;

  await Promise.all(resolvedCases.map(async (item) => {
    const sessionStat = await stat(item.sessionPath);
    if (!sessionStat.isFile()) throw new Error(`session_file_not_regular:${item.id}`);
  }));

  // This is process-local only. It does not edit .env or enable a deployed worker.
  process.env.PUBLISHING_WORKER_EXPERIMENTAL_PLATFORM_KEYS = [
    ...new Set(resolvedCases.map((item) => item.platform).filter((item) => item !== "wechat")),
  ].join(",");
  const { getPublisher } = await import("../publishing-worker/src/publishers/index.js");
  const statusPolls = boundedInteger(values.get("--status-polls"), 1, 0, 20);
  const statusIntervalMs = boundedInteger(values.get("--status-interval-ms"), 15_000, 1_000, 300_000);
  const concurrency = boundedInteger(values.get("--concurrency"), 1, 1, 4);

  type CaseSummary = Readonly<{
    caseId: string;
    platform: PlatformKey;
    outcome: "passed" | "action_required" | "failed";
    detail: string;
  }>;

  async function runCase(item: (typeof resolvedCases)[number]): Promise<CaseSummary> {
    try {
      const credentials = await loadCredentials(item.sessionPath);
      const publisher = getPublisher(item.platform);
      if (!publisher) throw new Error("publisher_missing");
      const localAuth = await publisher.checkAuth(credentials);
      if (!localAuth.ok) throw new Error("session_missing_platform_evidence");
      const input: PublicationInput = {
        targetId: `real-acceptance-${item.id}`,
        title: item.title,
        contentHtml: simpleHtml(item.contentText),
        contentText: item.contentText,
        tags: item.tags || [],
        assets: item.assets,
        credentials,
        publishMode: item.publishMode,
      };

      // Exactly one publish call per case. A timeout or unknown result is never retried,
      // because a second click could create duplicate public content.
      const result = await publisher.publish(input);
      process.stdout.write(`${JSON.stringify({ caseId: item.id, phase: "publish", result: safeResult(result) })}\n`);
      if (!result.success) {
        return {
          caseId: item.id,
          platform: item.platform,
          outcome: result.status === "action_required" || result.status === "auth_required"
            ? "action_required"
            : "failed",
          detail: result.safeErrorCode || result.status,
        };
      }

      if (item.publishMode === "draft" && result.status !== "drafted") {
        return { caseId: item.id, platform: item.platform, outcome: "failed", detail: "draft_result_unconfirmed" };
      }

      if (
        item.publishMode === "public"
        && result.status === "published"
        && !result.publicUrl
      ) {
        return { caseId: item.id, platform: item.platform, outcome: "failed", detail: "public_url_missing" };
      }

      if (item.publishMode === "public" && publisher.checkStatus && statusPolls > 0) {
        if (!result.managementUrl && !result.publicUrl && !result.externalPostId) {
          return { caseId: item.id, platform: item.platform, outcome: "failed", detail: "status_reference_missing" };
        }
        let finalStatus: PublicationStatusResult | undefined;
        for (let poll = 0; poll < statusPolls; poll += 1) {
          if (poll > 0) await new Promise((resolve) => setTimeout(resolve, statusIntervalMs));
          finalStatus = await publisher.checkStatus({
            credentials,
          externalPostId: result.externalPostId,
          expectedTitle: item.title,
          managementUrl: result.status === "published"
              ? result.publicUrl
              : result.managementUrl || result.publicUrl,
          });
          process.stdout.write(`${JSON.stringify({ caseId: item.id, phase: "status", poll: poll + 1, result: safeResult(finalStatus) })}\n`);
          if (["published", "failed", "auth_required"].includes(finalStatus.status)) break;
        }
        if (!finalStatus || finalStatus.status !== "published" || !finalStatus.publicUrl) {
          return {
            caseId: item.id,
            platform: item.platform,
            outcome: finalStatus?.status === "auth_required" ? "action_required" : "failed",
            detail: finalStatus?.safeErrorCode || finalStatus?.status || "status_unconfirmed",
          };
        }
      }
      if (
        item.publishMode === "public"
        && (!publisher.checkStatus || statusPolls === 0)
        && (result.status !== "published" || !result.publicUrl)
      ) {
        return { caseId: item.id, platform: item.platform, outcome: "failed", detail: "public_result_unconfirmed" };
      }
      return { caseId: item.id, platform: item.platform, outcome: "passed", detail: result.status };
    } catch (error) {
      const detail = error instanceof Error ? error.message : "acceptance_failed";
      return {
        caseId: item.id,
        platform: item.platform,
        outcome: detail.includes("session_") || detail.includes("authorization_")
          ? "action_required"
          : "failed",
        detail,
      };
    }
  }

  const summaries: CaseSummary[] = [];
  let cursor = 0;
  const workers = Array.from({ length: Math.min(concurrency, resolvedCases.length) }, async () => {
    while (cursor < resolvedCases.length) {
      const index = cursor;
      cursor += 1;
      summaries[index] = await runCase(resolvedCases[index]);
    }
  });
  await Promise.all(workers);

  const totals = summaries.reduce(
    (result, item) => ({ ...result, [item.outcome]: result[item.outcome] + 1 }),
    { passed: 0, action_required: 0, failed: 0 },
  );
  process.stdout.write(`${JSON.stringify({ phase: "summary", totals, cases: summaries }, null, 2)}\n`);
  if (totals.action_required || totals.failed) process.exitCode = 1;
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : "acceptance_failed";
  process.stderr.write(`ERROR ${message}\n`);
  process.exitCode = 1;
});
