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
  id: null,
  customer_id: "customer-1",
  owner_admin_id: null,
  owner_nickname: null,
  owner_phone_masked: "",
  version: 0,
  assigned_at: null,
};

const admin = {
  id: "admin-1",
  user_id: "user-1",
  nickname: "客户经理",
  phone_masked: "138****8000",
  is_superuser: false,
  admin_status: "active" as const,
  version: 1,
  logout_version: 1,
  role: null,
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
  it("submits two-person transfer with expected_version and keeps payload in memory", async () => {
    const approval = {
      approval_required: true as const,
      approval_id: "approval-assignment-1",
      status: "pending" as const,
      expires_at: "2026-08-02T00:00:00Z",
    };
    mocks.changeCustomerAssignment.mockResolvedValue(approval);
    const onApproval = vi.fn();
    const { container } = render(
      <CustomerAssignmentActions
        assignment={assignment}
        admins={[admin]}
        mode="two_person"
        onChanged={vi.fn()}
        onApproval={onApproval}
      />,
    );

    expect(container.textContent).toContain("未分配");
    expect(container.textContent).not.toContain("13800138000");

    fireEvent.mouseDown(screen.getByRole("combobox"));
    const option = await waitFor(() => {
      const candidate = Array.from(
        document.querySelectorAll<HTMLElement>(".ant-select-item-option"),
      ).find((item) => item.textContent?.includes("客户经理"));
      if (!candidate) throw new Error("admin option not rendered");
      return candidate;
    });
    await userEvent.click(option);
    expect(document.body.textContent).toContain("138****8000");
    await userEvent.click(container.querySelector("button") as HTMLButtonElement);
    await userEvent.type(screen.getByLabelText("操作原因"), "客户归属调整");
    await userEvent.click(screen.getByRole("button", { name: "发起审批" }));

    await waitFor(() =>
      expect(mocks.changeCustomerAssignment).toHaveBeenCalledWith(
        "customer-1",
        "admin-1",
        0,
        "客户归属调整",
        {
          confirmed: true,
          current_password: "",
          reason: "客户归属调整",
        },
      ),
    );
    expect(onApproval).toHaveBeenCalledWith(approval);
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
  });

  it("executes unassignment in confirm mode and reports the new safe assignment", async () => {
    const assigned = {
      ...assignment,
      id: "assignment-1",
      owner_admin_id: admin.id,
      owner_nickname: admin.nickname,
      owner_phone_masked: admin.phone_masked,
      version: 3,
    };
    const unassigned = { ...assignment, id: "assignment-1", version: 4 };
    mocks.changeCustomerAssignment.mockResolvedValue(unassigned);
    const onChanged = vi.fn();
    const { container } = render(
      <CustomerAssignmentActions
        assignment={assigned}
        admins={[admin]}
        mode="confirm"
        onChanged={onChanged}
        onApproval={vi.fn()}
      />,
    );

    fireEvent.mouseDown(screen.getByRole("combobox"));
    const option = await waitFor(() => {
      const candidate = Array.from(
        document.querySelectorAll<HTMLElement>(".ant-select-item-option"),
      ).find((item) => item.textContent?.includes("解除负责人"));
      if (!candidate) throw new Error("unassign option not rendered");
      return candidate;
    });
    await userEvent.click(option);
    await userEvent.click(container.querySelector("button") as HTMLButtonElement);
    await userEvent.type(screen.getByLabelText("操作原因"), "解除归属");
    await userEvent.click(screen.getByRole("button", { name: "确认执行" }));

    await waitFor(() => expect(onChanged).toHaveBeenCalledWith(unassigned));
  });

  it.each([403, 404, 409, 422, 429, 503])(
    "shows unified Chinese error for status %s",
    async (status) => {
      mocks.changeCustomerAssignment.mockRejectedValueOnce(new Error(`负责人变更失败 ${status}`));
      const { container } = render(
        <CustomerAssignmentActions
          assignment={assignment}
          admins={[admin]}
          mode="confirm"
          onChanged={vi.fn()}
          onApproval={vi.fn()}
        />,
      );
      fireEvent.mouseDown(screen.getByRole("combobox"));
      const option = await waitFor(() => {
        const candidate = Array.from(
          document.querySelectorAll<HTMLElement>(".ant-select-item-option"),
        ).find((item) => item.textContent?.includes("客户经理"));
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
