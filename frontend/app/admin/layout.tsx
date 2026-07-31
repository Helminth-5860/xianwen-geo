import type { ReactNode } from "react";

import { AdminCapabilityProvider } from "@/components/admin/admin-capability";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return <AdminCapabilityProvider>{children}</AdminCapabilityProvider>;
}
