import { get, post, write, type PageData } from "./auth-client";

export type Role = Readonly<{
  id: string;
  name: string;
  description: string;
  status: "active" | "inactive";
  data_scope: "own" | "role" | "all";
  version: number;
  permission_keys: string[];
}>;

export type AdminProfile = Readonly<{
  id: string;
  user_id: string;
  nickname: string;
  phone_masked: string;
  is_superuser: boolean;
  admin_status: "active" | "disabled" | "locked";
  version: number;
  logout_version: number;
  role: Role | null;
}>;

export type AdminContext = AdminProfile &
  Readonly<{
    admin_version: number;
    data_scope: "own" | "role" | "all";
    permission_keys: string[];
    menu_keys: string[];
  }>;

export type CatalogPermission = Readonly<{
  key: string;
  name: string;
  module: string;
  permission_type: "menu" | "action";
  status: "active" | "inactive";
  superuser_only: boolean;
}>;

export const getAdminContext = () => get<AdminContext>("/admin/me");
export const getAdmins = () => get<PageData<AdminProfile>>("/admin/admins");
export const getAdmin = (id: string) => get<AdminProfile>(`/admin/admins/${id}`);
export const createAdmin = (body: Record<string, unknown>) =>
  post<AdminProfile>("/admin/admins", body);
export const updateAdmin = (id: string, body: Record<string, unknown>) =>
  write<AdminProfile>("PATCH", `/admin/admins/${id}`, body);
export type RiskCredentials = Readonly<{
  confirmed: true;
  current_password: string;
}>;

export const changeAdminStatus = (
  id: string,
  action: string,
  expectedVersion: number,
  credentials: Partial<RiskCredentials> = {},
) =>
  post<import("./risk-client").RiskExecution<AdminProfile>>(`/admin/admins/${id}/${action}`, {
    expected_version: expectedVersion,
    ...credentials,
  });
export const changeAdminRole = (
  id: string,
  roleId: string,
  expectedVersion: number,
  credentials: RiskCredentials,
) =>
  post<import("./risk-client").RiskExecution<AdminProfile>>(`/admin/admins/${id}/role`, {
    role_id: roleId,
    expected_version: expectedVersion,
    ...credentials,
  });
export const getRoles = () => get<PageData<Role>>("/admin/roles");
export const getRole = (id: string) => get<Role>(`/admin/roles/${id}`);
export const createRole = (body: Record<string, unknown>) => post<Role>("/admin/roles", body);
export const updateRole = (id: string, body: Record<string, unknown>) =>
  write<Role>("PATCH", `/admin/roles/${id}`, body);
export const replaceRolePermissions = (
  id: string,
  permissionKeys: string[],
  expectedVersion: number,
  credentials: RiskCredentials,
) =>
  write<import("./risk-client").RiskExecution<Role>>("PUT", `/admin/roles/${id}/permissions`, {
    permission_keys: permissionKeys,
    expected_version: expectedVersion,
    ...credentials,
  });
export const disableRole = (id: string, expectedVersion: number, credentials: RiskCredentials) =>
  post<import("./risk-client").RiskExecution<Role>>(`/admin/roles/${id}/disable`, {
    expected_version: expectedVersion,
    ...credentials,
  });
export const getPermissions = () => get<CatalogPermission[]>("/admin/permissions");
export type AdminLoginPasswordResult =
  | Readonly<{ requires_2fa: true; challenge_id: string; expires_in: number }>
  | Readonly<{ requires_2fa: false; user: import("./auth-client").AccountUser }>;

export type IpAllowlistEntry = Readonly<{
  id: string;
  network_cidr: string;
  ip_version: 4 | 6;
  label: string;
  status: "active" | "inactive";
}>;

export type RoleSecurity = Readonly<{
  require_sms_2fa: boolean;
  ip_allowlist_enabled: boolean;
  security_version: number;
}>;

export type SuperuserSecurity = Readonly<{
  id: string;
  require_sms_2fa: true;
  ip_allowlist_enabled: boolean;
  security_version: number;
}>;

export const adminLoginWithPassword = (normalizedPhone: string, password: string) =>
  post<AdminLoginPasswordResult>("/admin/auth/login/password", {
    phone: normalizedPhone,
    password,
  });
export const sendAdminLoginSms = (challengeId: string) =>
  post<{ sent: true; expires_in: number; resend_after: number }>("/admin/auth/login/sms/send", {
    challenge_id: challengeId,
  });
export const verifyAdminLoginSms = (challengeId: string, smsCode: string) =>
  post<import("./auth-client").AccountUser>("/admin/auth/login/sms/verify", {
    challenge_id: challengeId,
    sms_code: smsCode,
  });
export const logoutAdmin = () => post<{ logged_out: true }>("/admin/auth/logout", {});
export const getRoleSecurity = (id: string) => get<RoleSecurity>(`/admin/roles/${id}/security`);
export const updateRoleSecurity = (id: string, body: Record<string, unknown>) =>
  write<RoleSecurity>("PATCH", `/admin/roles/${id}/security`, body);
export const getRoleIpAllowlist = (id: string) =>
  get<IpAllowlistEntry[]>(`/admin/roles/${id}/ip-allowlist`);
export const createRoleIpAllowlistEntry = (id: string, body: Record<string, unknown>) =>
  post<{ entry: IpAllowlistEntry; security_version: number }>(
    `/admin/roles/${id}/ip-allowlist`,
    body,
  );
export const updateRoleIpAllowlistEntry = (
  roleId: string,
  entryId: string,
  body: Record<string, unknown>,
) =>
  write<{ entry: IpAllowlistEntry; security_version: number }>(
    "PATCH",
    `/admin/roles/${roleId}/ip-allowlist/${entryId}`,
    body,
  );
export const getSuperuserSecurity = () => get<SuperuserSecurity>("/admin/security/superuser");
export const updateSuperuserSecurity = (body: Record<string, unknown>) =>
  write<SuperuserSecurity>("PATCH", "/admin/security/superuser", body);
export const getSuperuserIpAllowlist = () =>
  get<IpAllowlistEntry[]>("/admin/security/superuser/ip-allowlist");
export const createSuperuserIpAllowlistEntry = (body: Record<string, unknown>) =>
  post<{ entry: IpAllowlistEntry; security_version: number }>(
    "/admin/security/superuser/ip-allowlist",
    body,
  );
export const updateSuperuserIpAllowlistEntry = (entryId: string, body: Record<string, unknown>) =>
  write<{ entry: IpAllowlistEntry; security_version: number }>(
    "PATCH",
    `/admin/security/superuser/ip-allowlist/${entryId}`,
    body,
  );
export const forceLogoutAdmin = (
  id: string,
  expectedVersion: number,
  credentials: RiskCredentials,
) =>
  post<import("./risk-client").RiskExecution<{ logged_out: true; admin_id: string }>>(
    `/admin/admins/${id}/force-logout`,
    { expected_version: expectedVersion, ...credentials },
  );
