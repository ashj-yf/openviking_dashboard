import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type UserListItem = Schema["UserOut"];
export type UserCreateBody = Schema["UserCreateRequest"];
export type UserRoleBody = Schema["UserRoleRequest"];
export type UserResetPasswordBody = Schema["UserResetPasswordRequest"];
export type KeyRegenerateBody = Schema["KeyRegenerateRequest"];
export type UserSyncReport = Schema["UserSyncReport"];
export type UserProvisionBody = Schema["UserProvisionRequest"];

export const userApi = {
  list(params: { tenant_id?: number | null; keyword?: string | null } = {}): Promise<UserListItem[]> {
    return apiRequest<UserListItem[]>("GET", "/users", {
      query: { tenant_id: params.tenant_id, keyword: params.keyword },
    });
  },
  create(body: UserCreateBody): Promise<UserListItem> {
    return apiRequest<UserListItem>("POST", "/users", { body });
  },
  setRole(id: number, role: UserRoleBody["role"]): Promise<UserListItem> {
    return apiRequest<UserListItem>("PATCH", `/users/${id}/role`, { body: { role } });
  },
  resetPassword(id: number, body: UserResetPasswordBody): Promise<null> {
    return apiRequest<null>("POST", `/users/${id}/reset-password`, { body });
  },
  setEnabled(id: number, enabled: boolean): Promise<null> {
    return apiRequest<null>("POST", `/users/${id}/${enabled ? "enable" : "disable"}`);
  },
  regenerateKey(id: number, seed?: string): Promise<UserListItem> {
    return apiRequest<UserListItem>("POST", `/users/${id}/regenerate-key`, {
      body: { seed: seed || null },
    });
  },
  remove(id: number): Promise<null> {
    return apiRequest<null>("DELETE", `/users/${id}`);
  },
  sync(id: number): Promise<UserSyncReport> {
    return apiRequest<UserSyncReport>("POST", `/users/${id}/sync`);
  },
  /** LDAP JIT 用户开通：为自动建档用户补全团队归属与 OV 身份。 */
  provision(userId: number, payload: UserProvisionBody): Promise<UserListItem> {
    return apiRequest<UserListItem>("POST", `/users/${userId}/provision`, { body: payload });
  },
};
