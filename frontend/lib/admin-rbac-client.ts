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
  nickname: string;
  phone_masked: string;
  is_superuser: boolean;
  admin_status: "active" | "disabled" | "locked";
  version: number;
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
export const changeAdminStatus = (id: string, action: string, expectedVersion: number) =>
  post<AdminProfile>(`/admin/admins/${id}/${action}`, {
    expected_version: expectedVersion,
  });
export const getRoles = () => get<PageData<Role>>("/admin/roles");
export const getRole = (id: string) => get<Role>(`/admin/roles/${id}`);
export const createRole = (body: Record<string, unknown>) => post<Role>("/admin/roles", body);
export const updateRole = (id: string, body: Record<string, unknown>) =>
  write<Role>("PATCH", `/admin/roles/${id}`, body);
export const disableRole = (id: string, expectedVersion: number) =>
  post<Role>(`/admin/roles/${id}/disable`, { expected_version: expectedVersion });
export const getPermissions = () => get<CatalogPermission[]>("/admin/permissions");
