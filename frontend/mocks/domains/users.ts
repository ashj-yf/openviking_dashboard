import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type UserOut = Schema["UserOut"];
type UserSyncReport = Schema["UserSyncReport"];

/** setProvisionError/setUserActionError 注入的是测试夹具 JSON；在交予 MSW 响应前以此精确收窄（不用 any）。 */
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

export function makeUser(overrides: Partial<UserOut> = {}): UserOut {
  return {
    id: 3,
    username: "alice",
    role: "user",
    is_active: true,
    tenant_id: 1,
    account_id: "acme",
    ov_user_id: "alice",
    ov_role: "user",
    has_key: true,
    key_state: "current",
    key_synced_at: "2026-10-29T08:00:00Z",
    must_change_password: true,
    last_login_at: null,
    created_at: "2026-10-21T01:00:00Z",
    ...overrides,
  };
}

export function makeSyncReport(overrides: Partial<UserSyncReport> = {}): UserSyncReport {
  return {
    account_id: "acme",
    ov_user_id: "alice",
    ov_exists: true,
    local_ov_role: "user",
    ov_role: "user",
    consistent: true,
    ...overrides,
  };
}

let rows: UserOut[] = [];
let provisionError: { status: number; body: unknown } | null = null;
let actionError: { method: string; fragment: string; status: number; body: unknown } | null = null;
let syncReport: UserSyncReport = makeSyncReport();

export interface CapturedUserRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedUserRequest[] = [];

export function resetUsersMock(list: UserOut[] | null = [makeUser()]): void {
  rows = list === null ? [] : list;
  provisionError = null;
  actionError = null;
  captured.length = 0;
  syncReport = makeSyncReport();
}

export function setProvisionError(status: number, body: unknown): void {
  provisionError = { status, body };
}

export function setUserActionError(
  method: string,
  fragment: string,
  status: number,
  body: unknown,
): void {
  actionError = { method, fragment, status, body };
}

export function setUserSyncReport(report: UserSyncReport): void {
  syncReport = report;
}

export function getUserRequests(method?: string): CapturedUserRequest[] {
  return method ? captured.filter((r) => r.method === method) : [...captured];
}

function patchRow(id: number, patch: Partial<UserOut>): UserOut | null {
  let updated: UserOut | null = null;
  rows = rows.map((u) => {
    if (u.id !== id) return u;
    updated = { ...u, ...patch };
    return updated;
  });
  return updated;
}

function maybeActionError(method: string, url: string): Response | null {
  if (!actionError) return null;
  if (actionError.method === method && url.includes(actionError.fragment)) {
    return HttpResponse.json(actionError.body as JsonValue, { status: actionError.status });
  }
  return null;
}

export const userHandlers: HttpHandler[] = [
  http.get("*/api/v1/users", ({ request }) => {
    // R11：保留 GET list 捕获，筛选用例依赖 getUserRequests("GET")（同 tenants GET）。
    captured.push({ method: "GET", url: request.url, body: null });
    const params = new URL(request.url).searchParams;
    const tenantId = params.get("tenant_id");
    const keyword = params.get("keyword")?.toLowerCase() ?? "";
    let filtered = rows;
    if (tenantId) filtered = filtered.filter((u) => u.tenant_id === Number(tenantId));
    if (keyword) {
      filtered = filtered.filter(
        (u) =>
          u.username.toLowerCase().includes(keyword) ||
          (u.ov_user_id ?? "").toLowerCase().includes(keyword),
      );
    }
    return HttpResponse.json(filtered);
  }),
  http.post("*/api/v1/users", async ({ request }) => {
    const body = (await request.json()) as Schema["UserCreateRequest"];
    captured.push({ method: "POST", url: request.url, body });
    if (provisionError) {
      if (provisionError.status === 502) {
        const userId = (provisionError.body as { detail: { user_id: number } }).detail.user_id;
        rows = [
          ...rows,
          makeUser({
            id: userId,
            username: body.username,
            ov_user_id: body.ov_user_id ?? body.username,
            is_active: false,
            has_key: false,
            key_state: "pending",
            key_synced_at: null,
            tenant_id: body.tenant_id ?? 1,
            account_id: "acme",
          }),
        ];
      }
      return HttpResponse.json(provisionError.body as JsonValue, {
        status: provisionError.status,
      });
    }
    const created = makeUser({
      id: 77,
      username: body.username,
      ov_user_id: body.ov_user_id ?? body.username,
      role: body.role === "team_admin" ? "team_admin" : "user",
      ov_role: body.role === "team_admin" ? "admin" : "user",
      tenant_id: body.tenant_id ?? 1,
    });
    rows = [...rows, created];
    return HttpResponse.json(created, { status: 201 });
  }),
  http.patch("*/api/v1/users/:id/role", async ({ params, request }) => {
    const body = (await request.json()) as Schema["UserRoleRequest"];
    captured.push({ method: "PATCH", url: request.url, body });
    const error = maybeActionError("PATCH", "/role");
    if (error) return error;
    const updated = patchRow(Number(params.id), {
      role: body.role,
      ov_role: body.role === "team_admin" ? "admin" : "user",
    });
    return updated
      ? HttpResponse.json(updated)
      : HttpResponse.json({ detail: "用户不存在" }, { status: 404 });
  }),
  http.post("*/api/v1/users/:id/reset-password", async ({ params, request }) => {
    const body = await request.json();
    captured.push({ method: "POST", url: request.url, body });
    const error = maybeActionError("POST", "reset-password");
    if (error) return error;
    void params;
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/v1/users/:id/disable", async ({ params, request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    const error = maybeActionError("POST", "/disable");
    if (error) return error;
    patchRow(Number(params.id), { is_active: false });
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/v1/users/:id/enable", async ({ params, request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    const error = maybeActionError("POST", "/enable");
    if (error) return error;
    patchRow(Number(params.id), { is_active: true });
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/v1/users/:id/regenerate-key", async ({ params, request }) => {
    const body = (await request.json()) as Schema["KeyRegenerateRequest"];
    captured.push({ method: "POST", url: request.url, body });
    const error = maybeActionError("POST", "regenerate-key");
    if (error) return error;
    const updated = patchRow(Number(params.id), {
      has_key: true,
      key_state: "current",
      is_active: true,
      key_synced_at: "2026-10-29T10:00:00Z",
    });
    return updated
      ? HttpResponse.json(updated)
      : HttpResponse.json({ detail: "用户不存在" }, { status: 404 });
  }),
  http.delete("*/api/v1/users/:id", async ({ params, request }) => {
    captured.push({ method: "DELETE", url: request.url, body: null });
    const error = maybeActionError("DELETE", "/users/");
    if (error) return error;
    rows = rows.filter((u) => u.id !== Number(params.id));
    return new HttpResponse(null, { status: 204 });
  }),
  http.post("*/api/v1/users/:id/sync", async ({ request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    return HttpResponse.json(syncReport);
  }),
];
