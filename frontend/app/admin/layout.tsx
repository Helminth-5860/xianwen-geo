"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { AdminCapabilityProvider } from "@/components/admin/admin-capability";
import { AdminStepUpProvider } from "@/components/admin/admin-step-up";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  if (pathname === "/admin/login") return children;
  return (
    <AdminStepUpProvider>
      <AdminCapabilityProvider>{children}</AdminCapabilityProvider>
    </AdminStepUpProvider>
  );
}
