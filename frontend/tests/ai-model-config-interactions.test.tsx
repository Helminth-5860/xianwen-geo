// @vitest-environment jsdom

import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import AdminAIModelsPage from "../app/admin/models/page";
import { AdminCapabilityContext } from "../components/admin/admin-capability";
import type { AdminContext } from "../lib/admin-rbac-client";
import type { AIModelRuntimeConfig } from "../lib/ai-model-config-client";

const getAIModels = vi.fn();
const updateAIModelRuntimeConfig = vi.fn();
const changeAIModelEnabled = vi.fn();
const pauseAIModel = vi.fn();
const unpauseAIModel = vi.fn();

vi.mock("../lib/ai-model-config-client", async () => {
  const actual = await vi.importActual<typeof import("../lib/ai-model-config-client")>(
    "../lib/ai-model-config-client",
  );
  return {
    ...actual,
    getAIModels: (...args: unknown[]) => getAIModels(...args),
    updateAIModelRuntimeConfig: (...args: unknown[]) => updateAIModelRuntimeConfig(...args),
    changeAIModelEnabled: (...args: unknown[]) => changeAIModelEnabled(...args),
    pauseAIModel: (...args: unknown[]) => pauseAIModel(...args),
    unpauseAIModel: (...args: unknown[]) => unpauseAIModel(...args),
  };
});

const context: AdminContext = {
  id: "00000000-0000-0000-0000-000000000001",
  user_id: "00000000-0000-0000-0000-000000000002",
  nickname: "模型管理员",
  phone_masked: "+86 139****9000",
  is_superuser: false,
  admin_status: "active",
  version: 1,
  logout_version: 1,
  admin_version: 1,
  role: null,
  data_scope: "all",
  permission_keys: ["models.list", "models.manage"],
  menu_keys: ["menu.admin.models"],
  commercial_identity: "ADMIN",
  tenant_id: null,
  tenant_name: null,
};

const model: AIModelRuntimeConfig = {
  model_id: "00000000-0000-0000-0000-000000000010",
  provider_key: "deepseek",
  model_key: "deepseek",
  canonical_display_name: "DeepSeek",
  display_name: "DeepSeek",
  display_name_override: "",
  canonical_order: 10,
  purpose: "geo_detection",
  is_builtin: true,
  provider_model_id: "",
  api_version: "",
  enabled: false,
  sort_order: 10,
  network_access_enabled: false,
  web_search_failure_policy: "fail",
  timeout_seconds: 30,
  max_retries: 2,
  retry_base_seconds: 30,
  retry_backoff: "exponential",
  max_concurrency: 1,
  cost_unit: null,
  currency: "CNY",
  input_cost: null,
  output_cost: null,
  request_cost: null,
  paused: false,
  pause_reason: "",
  version: 3,
  created_at: "2026-08-17T00:00:00Z",
  updated_at: "2026-08-17T00:00:00Z",
};

const renderPage = (permissions = context.permission_keys) =>
  render(
    <AdminCapabilityContext.Provider value={{ ...context, permission_keys: permissions }}>
      <AdminAIModelsPage />
    </AdminCapabilityContext.Provider>,
  );

beforeAll(() => {
  const nativeGetComputedStyle = window.getComputedStyle.bind(window);
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    nativeGetComputedStyle(element),
  );
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: () => ({
      matches: false,
      addListener: () => undefined,
      removeListener: () => undefined,
      addEventListener: () => undefined,
      removeEventListener: () => undefined,
      dispatchEvent: () => false,
    }),
  });
});

beforeEach(() => {
  getAIModels.mockResolvedValue([model]);
  updateAIModelRuntimeConfig.mockResolvedValue({ ...model, timeout_seconds: 45, version: 4 });
  changeAIModelEnabled.mockResolvedValue({ ...model, enabled: true, version: 4 });
  pauseAIModel.mockResolvedValue({ ...model, paused: true, version: 4 });
  unpauseAIModel.mockResolvedValue({ ...model, paused: false, version: 4 });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("模型运行配置后台真实交互", () => {
  it("展示固定模型和无密钥边界", async () => {
    renderPage();
    expect(await screen.findByText("DeepSeek")).toBeTruthy();
    expect(screen.getByText(/查看模型运行状态/)).toBeTruthy();
    expect(screen.queryByLabelText(/API Key/)).toBeNull();
    expect(screen.queryByRole("button", { name: /新增模型/ })).toBeNull();
  });

  it("编辑运行配置时携带当前版本并提交受控字段", async () => {
    renderPage();
    const row = (await screen.findByText("DeepSeek")).closest("tr");
    if (!row) throw new Error("missing model row");
    await userEvent.click(within(row).getByRole("button", { name: /编\s*辑/ }));
    const dialog = screen.getByRole("dialog");
    const timeout = within(dialog).getByLabelText("超时（秒）");
    await userEvent.clear(timeout);
    await userEvent.type(timeout, "45");
    await userEvent.click(within(dialog).getByRole("button", { name: /保\s*存/ }));
    await waitFor(() =>
      expect(updateAIModelRuntimeConfig).toHaveBeenCalledWith(
        expect.objectContaining({ model_id: model.model_id, version: 3 }),
        expect.objectContaining({ timeout_seconds: 45, cost_unit: null }),
      ),
    );
  });

  it("启用和暂停分别携带当前版本与原因", async () => {
    renderPage();
    const row = (await screen.findByText("DeepSeek")).closest("tr");
    if (!row) throw new Error("missing model row");
    await userEvent.click(within(row).getByRole("button", { name: /启\s*用/ }));
    await waitFor(() => expect(changeAIModelEnabled).toHaveBeenCalledWith(model, "enable"));

    await userEvent.click(within(row).getByRole("button", { name: /暂\s*停/ }));
    const dialog = screen.getByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("暂停原因"), "供应商维护");
    await userEvent.click(within(dialog).getByRole("button", { name: /确\s*认\s*暂\s*停/ }));
    await waitFor(() => expect(pauseAIModel).toHaveBeenCalledWith(model, "供应商维护"));
  });

  it("无管理权限时写操作全部禁用", async () => {
    renderPage(["models.list"]);
    const row = (await screen.findByText("DeepSeek")).closest("tr");
    if (!row) throw new Error("missing model row");
    for (const name of [/编\s*辑/, /启\s*用/, /暂\s*停/]) {
      expect(within(row).getByRole("button", { name })).toHaveProperty("disabled", true);
    }
  });
});
