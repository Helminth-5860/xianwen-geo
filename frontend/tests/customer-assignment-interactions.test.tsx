// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

import { CustomerAssignmentActions } from "../components/admin/customer-assignment-actions";

const mocks = vi.hoisted(() => ({
  changeCustomerAssignment: vi.fn(),
}));

vi.mock("@/lib/admin-rbac-client", () => ({
  changeCustomerAssignment: mocks.changeCustomerAssignment,
}));

const assignment = {
  id: "assignment-1",
  customer_id: "customer-1",
  owner_admin_id: "admin-1",
  owner_nickname: "客户经理甲",
  owner_phone_masked: "138****8000",
  version: 1,
  assigned_at: null,
};

const admin = {
  id: "admin-1",
  user_id: "user-1",
  nickname: "客户经理甲",
  phone_masked: "138****8000",
  is_superuser: false,
  admin_status: "active" as const,
  version: 1,
  logout_version: 1,
  role: null,
  tenant_id: null,
  tenant_name: null,
};

const secondAdmin = {
  ...admin,
  id: "admin-2",
  user_id: "user-2",
  nickname: "客户经理乙",
  phone_masked: "139****9000",
};

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
    value: vi.fn().mockImplementation(() => ({
      matches: false,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
});

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(cleanup);

describe("customer assignment high-risk entry", () => {
  it("confirms transfer with expected_version and keeps payload in memory", async () => {
    const transferred = {
      ...assignment,
      owner_admin_id: secondAdmin.id,
      owner_nickname: secondAdmin.nickname,
      owner_phone_masked: secondAdmin.phone_masked,
      version: 2,
    };
    mocks.changeCustomerAssignment.mockResolvedValue(transferred);
    const onChanged = vi.fn();
    const { container } = render(
      <CustomerAssignmentActions
        assignment={assignment}
        admins={[admin, secondAdmin]}
        mode="confirm"
        onChanged={onChanged}
      />,
    );

    expect(container.textContent).toContain("客户经理甲");
    expect(container.textContent).not.toContain("13800138000");

    fireEvent.mouseDown(screen.getByRole("combobox"));
    const option = await waitFor(() => {
      const candidate = Array.from(
        document.querySelectorAll<HTMLElement>(".ant-select-item-option"),
      ).find((item) => item.textContent?.includes("客户经理乙"));
      if (!candidate) throw new Error("admin option not rendered");
      return candidate;
    });
    await userEvent.click(option);
    expect(document.body.textContent).toContain("139****9000");
    await userEvent.click(container.querySelector("button") as HTMLButtonElement);
    await userEvent.type(screen.getByLabelText("操作原因"), "客户归属调整");
    await userEvent.click(screen.getByRole("button", { name: "确认执行" }));

    await waitFor(() =>
      expect(mocks.changeCustomerAssignment).toHaveBeenCalledWith(
        "customer-1",
        "admin-2",
        1,
        "客户归属调整",
        {
          confirmed: true,
          current_password: "",
          reason: "客户归属调整",
        },
      ),
    );
    expect(onChanged).toHaveBeenCalledWith(transferred);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("executes non-null owner transfer in confirm mode", async () => {
    const transferred = {
      ...assignment,
      owner_admin_id: secondAdmin.id,
      owner_nickname: secondAdmin.nickname,
      owner_phone_masked: secondAdmin.phone_masked,
      version: 2,
    };
    mocks.changeCustomerAssignment.mockResolvedValue(transferred);
    const onChanged = vi.fn();
    const { container } = render(
      <CustomerAssignmentActions
        assignment={assignment}
        admins={[admin, secondAdmin]}
        mode="confirm"
        onChanged={onChanged}
      />,
    );

    fireEvent.mouseDown(screen.getByRole("combobox"));
    const option = await waitFor(() => {
      const candidate = Array.from(
        document.querySelectorAll<HTMLElement>(".ant-select-item-option"),
      ).find((item) => item.textContent?.includes("客户经理乙"));
      if (!candidate) throw new Error("transfer option not rendered");
      return candidate;
    });
    await userEvent.click(option);
    await userEvent.click(container.querySelector("button") as HTMLButtonElement);
    await userEvent.type(screen.getByLabelText("操作原因"), "转交归属");
    await userEvent.click(screen.getByRole("button", { name: "确认执行" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(transferred));
  });

  it.each([403, 404, 409, 422, 429, 503])(
    "shows unified Chinese error for status %s",
    async (status) => {
      mocks.changeCustomerAssignment.mockRejectedValueOnce(new Error(`负责人变更失败 ${status}`));
      const { container } = render(
        <CustomerAssignmentActions
          assignment={assignment}
          admins={[admin, secondAdmin]}
          mode="confirm"
          onChanged={vi.fn()}
        />,
      );
      fireEvent.mouseDown(screen.getByRole("combobox"));
      const option = await waitFor(() => {
        const candidate = Array.from(
          document.querySelectorAll<HTMLElement>(".ant-select-item-option"),
        ).find((item) => item.textContent?.includes("客户经理乙"));
        if (!candidate) throw new Error("admin option not rendered");
        return candidate;
      });
      await userEvent.click(option);
      await userEvent.click(container.querySelector("button") as HTMLButtonElement);
      await userEvent.type(screen.getByLabelText("操作原因"), "归属调整");
      await userEvent.click(screen.getByRole("button", { name: "确认执行" }));
      expect(await screen.findByText(`负责人变更失败 ${status}`)).toBeTruthy();
    },
  );
});
