import { redirect } from "next/navigation";

export default function LegacyRoleDetailPage() {
  redirect("/admin/admins");
  return null;
}
