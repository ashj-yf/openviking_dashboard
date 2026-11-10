import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type TenantListItem = Schema["TenantListItem"];
type TenantDetail = Schema["TenantDetailOut"];
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

export function makeTenantDetail(overrides: Partial<TenantDetail> = {}): TenantDetail {
  return {
    ...makeTenant(),
    ov_account: { account_id: "acme", users_count: 3, status: "active" },
    configuration: { memory: { enabled: true }, version: 9 },
    settings: { theme: "default" },
    ov_error: null,
    ...overrides,
  };
}

let rows: TenantListItem[] = [];
let listError: { status: number; body: unknown } | null = null;
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
let detailById: Record<number, TenantDetail> = { 1: makeTenantDetail() };

export interface CapturedRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedRequest[] = [];

export function resetTenantsMock(list: TenantListItem[] | null = [makeTenant()]): void {
  rows = list === null ? [] : list;
  listError = null;
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
  detailById = { 1: makeTenantDetail() };
}

export function setCreateError(status: number, body: unknown): void {
  createError = { status, body };
}

/** 注入 GET /tenants 列表错误（须在 resetTenantsMock 之后调用，reset 会清空）。 */
export function setListError(status: number, body: unknown): void {
  listError = { status, body };
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

export function setTenantDetail(id: number, detail: TenantDetail | null): void {
  if (detail === null) delete detailById[id];
  else detailById[id] = detail;
}

export const tenantListHandlers: HttpHandler[] = [
  http.get("*/api/v1/tenants", ({ request }) => {
    // R7：保留 GET list 捕获，T4 搜索防抖用例依赖 getTenantRequests("GET")。
    captured.push({ method: "GET", url: request.url, body: null });
    if (listError) return HttpResponse.json(listError.body as JsonValue, { status: listError.status });
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
  http.get("*/api/v1/tenants/:id", ({ params }) => {
    const detail = detailById[Number(params.id)];
    return detail
      ? HttpResponse.json(detail)
      : HttpResponse.json({ detail: "团队不存在" }, { status: 404 });
  }),
  http.patch("*/api/v1/tenants/:id", async ({ params, request }) => {
    const id = Number(params.id);
    const body = (await request.json()) as Record<string, unknown>;
    captured.push({ method: "PATCH", url: request.url, body });
    const current = detailById[id];
    if (!current) return HttpResponse.json({ detail: "团队不存在" }, { status: 404 });
    const patched: TenantDetail = { ...current, ...body };
    detailById[id] = patched;
    rows = rows.map((t) => (t.id === id ? { ...t, ...body } : t));
    return HttpResponse.json(patched);
  }),
  http.delete("*/api/v1/tenants/:id", async ({ request, params }) => {
    const body = (await request.json()) as unknown;
    captured.push({ method: "DELETE", url: request.url, body });
    const id = Number(params.id);
    rows = rows.filter((t) => t.id !== id);
    delete detailById[id];
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/v1/tenants/:id/sync", ({ request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    return HttpResponse.json(syncReport);
  }),
];
