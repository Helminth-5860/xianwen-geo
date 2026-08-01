"use client";

import { Alert, Button, Space, Spin } from "antd";
import Link from "next/link";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { getAdminContext, type AdminContext } from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";

export const AdminCapabilityContext = createContext<AdminContext | null>(null);

const MENU_ITEMS = [
  ["menu.admin.dashboard", "/admin", "工作台"],
  ["menu.admin.users", "/admin/users", "用户"],
  ["menu.admin.admins", "/admin/admins", "管理员"],
  ["menu.admin.roles", "/admin/roles", "角色"],
  ["menu.admin.admins", "/admin/security", "安全策略"],
] as const;

export function AdminCapabilityProvider({ children }: { children: ReactNode }) {
  const [context, setContext] = useState<AdminContext | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void getAdminContext()
      .then(setContext)
      .catch((reason) => setError(userMessage(reason)));
  }, []);
  if (error) return <Alert type="error" showIcon message="无权访问后台" description={error} />;
  if (!context) return <Spin description="正在校验后台权限" />;
  return (
    <AdminCapabilityContext.Provider value={context}>
      <nav aria-label="后台菜单">
        <Space wrap>
          {MENU_ITEMS.filter(([key]) => context.menu_keys.includes(key)).map(
            ([key, href, label]) => (
              <Link key={key} href={href}>
                <Button type="text">{label}</Button>
              </Link>
            ),
          )}
        </Space>
      </nav>
      {children}
    </AdminCapabilityContext.Provider>
  );
}

export const useAdminCapabilities = () => useContext(AdminCapabilityContext);
