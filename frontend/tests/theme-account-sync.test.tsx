// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  AppThemeProvider,
  useAppTheme,
} from "../components/theme/app-theme-provider";
import { ThemeAccountSync } from "../components/theme/theme-account-sync";

const mocks = vi.hoisted(() => ({
  updateAppearance: vi.fn(),
}));

let accountAppearance = { mode: "dark" as const, accent: "purple" as const };

vi.mock("../components/subject-workspace-context", () => ({
  useSubjectWorkspace: () => ({
    user: {
      id: "user-1",
      nickname: "主题用户",
      appearance: accountAppearance,
    },
  }),
}));

vi.mock("../lib/auth-client", () => ({
  updateAppearance: (...args: unknown[]) => mocks.updateAppearance(...args),
}));

function ThemeState() {
  const theme = useAppTheme();
  return (
    <div>
      <output data-testid="account-theme-state">
        {theme.mode}:{theme.accent}:{theme.savedAppearance.mode}:{theme.savedAppearance.accent}
      </output>
      <button
        type="button"
        onClick={() => void theme.saveAppearance({ mode: "dark", accent: "green" })}
      >
        保存账号外观
      </button>
    </div>
  );
}

function renderAccountTheme() {
  return render(
    <AppThemeProvider
      initialAppearance={{ mode: "light", accent: "blue" }}
      initialResolvedTheme="light"
    >
      <ThemeAccountSync />
      <ThemeState />
    </AppThemeProvider>,
  );
}

beforeEach(() => {
  window.localStorage.clear();
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: () => ({
      matches: false,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  accountAppearance = { mode: "dark", accent: "purple" };
  mocks.updateAppearance.mockResolvedValue({
    appearance: { mode: "dark", accent: "green" },
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("账号外观同步", () => {
  it("登录后使用账号保存的外观覆盖本机默认值", async () => {
    renderAccountTheme();

    await waitFor(() =>
      expect(screen.getByTestId("account-theme-state").textContent).toBe(
        "dark:purple:dark:purple",
      ),
    );
    expect(document.documentElement.dataset.colorTheme).toBe("purple");
  });

  it("保存外观时写入当前账号并采用服务端确认结果", async () => {
    renderAccountTheme();
    await waitFor(() =>
      expect(screen.getByTestId("account-theme-state").textContent).toBe(
        "dark:purple:dark:purple",
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "保存账号外观" }));

    await waitFor(() =>
      expect(mocks.updateAppearance).toHaveBeenCalledWith({ mode: "dark", accent: "green" }),
    );
    await waitFor(() =>
      expect(screen.getByTestId("account-theme-state").textContent).toBe(
        "dark:green:dark:green",
      ),
    );
  });
});
