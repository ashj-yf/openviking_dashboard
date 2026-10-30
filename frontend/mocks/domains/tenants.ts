import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type TenantListItem = Schema["TenantListItem"];
type TenantCreated = Schema["TenantCreatedOut"];
type TenantSyncReport = Schema["TenantSyncReport"];

/** setCreateError 注入的是测试夹具 JSON；在交予 MSW 响应前以此精确收窄（不用 any）。 */
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export function makeTenant(overrides: Partial<TenantListItem> = {}): TenantListItem {
  return {
    id: 1,
    account_id: "acme",
    display_name: "Acme 团队",
    remark: null,
    admin_user_id: "boss",
    user_count: 3,
    synced_at: "2026-10-29T08:00:00Z",
    created_at: "2026-10-20T03:24:15Z",
    ...overrides,
  };
}

export function makeSyncReport(overrides: Partial<TenantSyncReport> = {}): TenantSyncReport {
  return {
    account_id: "acme",
    ov_user_count: 5,
    local_user_count: 3,
    matched: 3,
    missing_local: [{ ov_user_id: "carol", ov_role: "user", username: null }],
    extra_local: [],
    synced_at: "2026-10-29T09:00:00Z",
    ...overrides,
  };
}

let rows: TenantListItem[] = [];
let createError: { status: number; body: unknown } | null = null;
let createdPayload: TenantCreated = {
  id: 1,
  account_id: "acme",
  admin_user_id: "boss",
  team_admin_id: 11,
  team_admin_username: "boss",
  key_provisioned: true,
};
let syncReport: TenantSyncReport = makeSyncReport();

export interface CapturedRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedRequest[] = [];

export function resetTenantsMock(list: TenantListItem[] | null = [makeTenant()]): void {
  rows = list === null ? [] : list;
  createError = null;
  captured.length = 0;
  createdPayload = {
    id: 99,
    account_id: "acme",
    admin_user_id: "boss",
    team_admin_id: 11,
    team_admin_username: "boss",
    key_provisioned: true,
  };
  syncReport = makeSyncReport();
}

export function setCreateError(status: number, body: unknown): void {
  createError = { status, body };
}

export function setCreatedPayload(payload: TenantCreated): void {
  createdPayload = payload;
}

export function setSyncReport(report: TenantSyncReport): void {
  syncReport = report;
}

export function getTenantRequests(method?: string): CapturedRequest[] {
  return method ? captured.filter((r) => r.method === method) : [...captured];
}

export const tenantListHandlers: HttpHandler[] = [
  http.get("*/api/v1/tenants", ({ request }) => {
    captured.push({ method: "GET", url: request.url, body: null });
    const q = new URL(request.url).searchParams.get("q")?.toLowerCase() ?? "";
    const filtered = q
      ? rows.filter(
          (t) =>
            t.account_id.toLowerCase().includes(q) ||
            (t.display_name ?? "").toLowerCase().includes(q) ||
            t.admin_user_id.toLowerCase().includes(q),
        )
      : rows;
    return HttpResponse.json(filtered);
  }),
  http.post("*/api/v1/tenants", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    captured.push({ method: "POST", url: request.url, body });
    if (createError)
      return HttpResponse.json(createError.body as JsonValue, { status: createError.status });
    return HttpResponse.json(createdPayload, { status: 201 });
  }),
  http.delete("*/api/v1/tenants/:id", async ({ request, params }) => {
    const body = (await request.json()) as unknown;
    captured.push({ method: "DELETE", url: request.url, body });
    const id = Number(params.id);
    rows = rows.filter((t) => t.id !== id);
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/v1/tenants/:id/sync", ({ request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    return HttpResponse.json(syncReport);
  }),
];
