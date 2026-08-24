import { redirect } from "next/navigation";

export default function LegacyCompanyManagementPage() {
  redirect("/admin/admins");
  return null;
}
