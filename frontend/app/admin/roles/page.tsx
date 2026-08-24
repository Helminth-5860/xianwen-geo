import { redirect } from "next/navigation";

export default function LegacyRoleManagementPage() {
  redirect("/admin/admins");
  return null;
}
