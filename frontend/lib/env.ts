type EnvironmentSource = Record<string, string | undefined>;

export type PublicEnvironment = Readonly<{
  appEnvironment: "local" | "test" | "production";
  apiBaseUrl: string;
}>;

const LOCAL_API_BASE_URL = "http://localhost:8000/api/v1";
const PUBLIC_SECRET_PATTERN = /(API_KEY|SECRET|TOKEN|PASSWORD|PRIVATE_KEY)/i;

export function readPublicEnvironment(source: EnvironmentSource): PublicEnvironment {
  const appEnvironment = source.NEXT_PUBLIC_APP_ENV ?? "local";
  if (!["local", "test", "production"].includes(appEnvironment)) {
    throw new Error("NEXT_PUBLIC_APP_ENV 必须是 local、test 或 production");
  }

  for (const [name, value] of Object.entries(source)) {
    if (name.startsWith("NEXT_PUBLIC_") && value && PUBLIC_SECRET_PATTERN.test(name)) {
      throw new Error(`${name} 不得作为前端公开变量`);
    }
  }

  const rawApiBaseUrl = source.NEXT_PUBLIC_API_BASE_URL || LOCAL_API_BASE_URL;
  if (appEnvironment === "production" && !source.NEXT_PUBLIC_API_BASE_URL) {
    throw new Error("production 必须配置 NEXT_PUBLIC_API_BASE_URL");
  }

  const apiBaseUrl = new URL(rawApiBaseUrl);
  if (!["http:", "https:"].includes(apiBaseUrl.protocol)) {
    throw new Error("NEXT_PUBLIC_API_BASE_URL 必须使用 HTTP(S)");
  }
  if (appEnvironment === "production" && apiBaseUrl.protocol !== "https:") {
    throw new Error("production 的 API 地址必须使用 HTTPS");
  }

  return Object.freeze({
    appEnvironment: appEnvironment as PublicEnvironment["appEnvironment"],
    apiBaseUrl: apiBaseUrl.toString().replace(/\/$/, ""),
  });
}

export const publicEnvironment = readPublicEnvironment({
  NEXT_PUBLIC_APP_ENV: process.env.NEXT_PUBLIC_APP_ENV,
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL,
});
