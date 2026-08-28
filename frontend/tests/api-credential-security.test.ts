import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const pageSource = readFileSync(new URL("../app/admin/models/page.tsx", import.meta.url), "utf8");
const clientSource = readFileSync(
  new URL("../lib/api-credential-client.ts", import.meta.url),
  "utf8",
);

describe("XW-0403 API credential admin frontend security contract", () => {
  it("renders credential management only behind superuser credential capability", () => {
    expect(pageSource).toContain("capabilities?.is_superuser");
    expect(pageSource).toContain('"api_credentials.manage"');
    expect(pageSource).toContain('title="接口凭据"');
  });

  it("uses password inputs, resets plaintext forms, and never references ciphertext", () => {
    expect(pageSource).toContain("<Input.Password");
    expect(pageSource).toContain('autoComplete="new-password"');
    expect(pageSource).toContain("credentialForm.resetFields()");
    expect(pageSource).toContain("rotateForm.resetFields()");
    expect(pageSource).not.toContain("secret_reference");
    expect(clientSource).not.toContain("secret_reference");
  });

  it("uses only the frozen create, rotate, and local test API endpoints", () => {
    expect(clientSource).toContain('"/admin/api-credentials"');
    expect(clientSource).toContain("/rotate");
    expect(clientSource).toContain("/test");
    expect(clientSource).not.toContain("/reveal");
    expect(pageSource).toContain("未执行真实 Provider 网络验证");
  });
});
