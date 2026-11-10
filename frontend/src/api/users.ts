import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type UserListItem = Schema["UserOut"];
export type UserCreateBody = Schema["UserCreateRequest"];
export type UserSyncReport = Schema["UserSyncReport"];

export const userApi = {
  list(params: { tenant_id?: number | null; keyword?: string | null } = {}): Promise<UserListItem[]> {
    return apiRequest<UserListItem[]>("GET", "/users", {
      query: { tenant_id: params.tenant_id, keyword: params.keyword },
    });
  },
  create(body: UserCreateBody): Promise<UserListItem> {
    return apiRequest<UserListItem>("POST", "/users", { body });
  },
};
