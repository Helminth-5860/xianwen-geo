type EnvironmentSource = Record<string, string | undefined>;

export type PublicEnvironment = Readonly<{
  appEnvironment: "local" | "test" | "staging" | "production";
  apiBaseUrl: string;
}>;

const LOCAL_API_BASE_URL = "http://localhost:8000/api/v1";
const PUBLIC_SECRET_PATTERN = /(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)/i;
const REMOTE_ENVIRONMENTS = new Set(["staging", "production"]);

function normalizeApiBaseUrl(rawValue: string, *, remote: boolean): string {
  const raw = rawValue.trim();
  if (!raw) throw new Error("NEXT_PUBLIC_API_BASE_URL 不能为空");

  if (raw.startsWith("/")) {
    if (raw.startsWith("//")) {
      throw new Error("NEXT_PUBLIC_API_BASE_URL 同源路径必须以单个 / 开头");
    }
    return raw.replace(/\/$/, "");
  }

  const apiBaseUrl = new URL(raw);
  if (!["http:", "https:"].includes(apiBaseUrl.protocol)) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL 必须使用 HTTP(S) 或同源 / 路径");
  }
  if (remote && apiBaseUrl.protocol !== "https:") {
    throw new Error("staging / production 的绝对 API 地址必须使用 HTTPS；推荐使用同源 /api/v1");
  }
  return apiBaseUrl.toString().replace(/\/$/, "");
}

export function readPublicEnvironment(source: EnvironmentSource): PublicEnvironment {
  const appEnvironment = source.NEXT_PUBLIC_APP_ENV ?? "local";
  if (!["local", "test", "staging", "production"].includes(appEnvironment)) {
    throw new Error("NEXT_PUBLIC_APP_ENV 必须是 local、test、staging 或 production");
  }

  for (const [name, value] of Object.entries(source)) {
    if (name.startsWith("NEXT_PUBLIC_") && value && PUBLIC_SECRET_PATTERN.test(name)) {
      throw new Error(`${name} 不得作为前端公开变量`);
    }
  }

  const isRemoteEnvironment = REMOTE_ENVIRONMENTS.has(appEnvironment);
  const configuredApiBaseUrl = source.NEXT_PUBLIC_API_BASE_URL;
  if (isRemoteEnvironment && !configuredApiBaseUrl) {
    throw new Error(`${appEnvironment} 必须配置 NEXT_PUBLIC_API_BASE_URL`);
  }

  const apiBaseUrl = normalizeApiBaseUrl(
    configuredApiBaseUrl || LOCAL_API_BASE_URL,
    { remote: isRemoteEnvironment },
  );

  return Object.freeze({
    appEnvironment: appEnvironment as PublicEnvironment["appEnvironment"],
    apiBaseUrl,
  });
}

export const publicEnvironment = readPublicEnvironment({
  NEXT_PUBLIC_APP_ENV: process.env.NEXT_PUBLIC_APP_ENV,
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
});
