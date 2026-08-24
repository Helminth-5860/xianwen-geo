"use client";

import { Alert, Button, Spin } from "antd";
import Link from "next/link";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { AdminConsoleShell } from "@/components/admin/admin-console-shell";
import { getAdminContext, type AdminContext } from "@/lib/admin-rbac-client";
import { userMessage } from "@/lib/auth-client";

export const AdminCapabilityContext = createContext<AdminContext | null>(null);

export function AdminCapabilityProvider({ children }: { children: ReactNode }) {
  const [context, setContext] = useState<AdminContext | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    void getAdminContext()
      .then(setContext)
      .catch((reason) => setError(userMessage(reason)));
  }, []);
  if (error)
    return (
      <div className="admin-console-state">
        <Alert
          type="error"
          showIcon
          title="无权访问后台"
          description={error}
          action={
            <Link href="/admin/login">
              <Button type="primary">前往登录</Button>
            </Link>
          }
        />
      </div>
    );
  if (!context)
    return (
      <div className="admin-console-state">
        <Spin description="正在进入平台运营中心" size="large" />
      </div>
    );
  return (
    <AdminCapabilityContext.Provider value={context}>
      <AdminConsoleShell context={context}>{children}</AdminConsoleShell>
    </AdminCapabilityContext.Provider>
  );
}

export const useAdminCapabilities = () => useContext(AdminCapabilityContext);
