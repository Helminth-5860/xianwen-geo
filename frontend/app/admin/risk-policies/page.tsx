import { redirect } from "next/navigation";

export default function RetiredRiskPolicyPage() {
  redirect("/admin/settings");
  return null;
}
