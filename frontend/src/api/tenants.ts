import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type TenantListItem = Schema["TenantListItem"];
export type TenantDetail = Schema["TenantDetailOut"];
export type TenantCreateBody = Schema["TenantCreateRequest"];
export type TenantUpdateBody = Schema["TenantUpdateRequest"];
export type TenantCreated = Schema["TenantCreatedOut"];
export type TenantSyncReport = Schema["TenantSyncReport"];

export const tenantApi = {
  list(q?: string): Promise<TenantListItem[]> {
    return apiRequest<TenantListItem[]>("GET", "/tenants", { query: { q } });
  },
  create(body: TenantCreateBody): Promise<TenantCreated> {
    return apiRequest<TenantCreated>("POST", "/tenants", { body });
  },
  get(id: number): Promise<TenantDetail> {
    return apiRequest<TenantDetail>("GET", `/tenants/${id}`);
  },
  update(id: number, body: TenantUpdateBody): Promise<TenantListItem> {
    return apiRequest<TenantListItem>("PATCH", `/tenants/${id}`, { body });
  },
  remove(id: number): Promise<null> {
    return apiRequest<null>("DELETE", `/tenants/${id}`, { body: { confirm: true } });
  },
  sync(id: number): Promise<TenantSyncReport> {
    return apiRequest<TenantSyncReport>("POST", `/tenants/${id}/sync`);
  },
};
