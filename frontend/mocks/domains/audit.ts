import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type AuditLog = Schema["AuditLogOut"];
type AuditLogPage = Schema["AuditLogPageOut"];

/** setAuditError / setOvAuditError 注入的是测试夹具 JSON；在交予 MSW 响应前以此精确收窄（不用 any，同 tenants.ts）。 */
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** 后端全部审计 action 常量（盘点自 app/ 各 audit_service.record 调用点；筛选域取其前缀）。 */
export const AUDIT_ACTIONS: readonly string[] = [
  "auth.login.success",
  "auth.login.fail",
  "auth.logout",
  "auth.password.change",
  "auth.ldap.bind.success",
  "auth.ldap.bind.fail",
  "auth.ldap.jit_create",
  "auth.ldap.jit_rejected",
  "tenant.create",
  "tenant.update",
  "tenant.delete",
  "tenant.delete.fail",
  "tenant.sync",
  "user.create",
  "user.provision",
  "user.enable",
  "user.disable",
  "user.delete",
  "user.delete.fail",
  "user.role.change",
  "user.password.reset",
  "user.key.issue_failed",
  "key.view",
  "key.copy",
  "key.regenerate",
  "ldap.config.update",
  "ldap.config.test",
];

export function makeAuditLog(overrides: Partial<AuditLog> = {}): AuditLog {
  return {
    id: 1,
    actor_user_id: 1,
    actor_name: "root",
    action: "tenant.create",
    target_type: "tenant",
    target_id: "acme",
    detail: { account_id: "acme" },
    ip: "10.0.0.8",
    created_at: "2026-11-01T08:00:00Z",
    ...overrides,
  };
}

/** 默认夹具：覆盖全部 action 域的多行样本，保证无显式 reset 的路由冒烟测试也能渲染行。 */
function defaultRows(): AuditLog[] {
  return AUDIT_ACTIONS.map((action, index) =>
    makeAuditLog({
      id: index + 1,
      actor_name: index % 2 === 0 ? "root" : "boss",
      action,
      target_type: action.startsWith("tenant.") ? "tenant" : "dashboard_user",
      target_id: action.startsWith("tenant.") ? "acme" : String(index + 1),
      detail: index % 3 === 0 ? null : { seq: index + 1 },
      ip: index % 2 === 0 ? "10.0.0.8" : "192.168.1.2",
      created_at: `2026-11-01T${String(index % 24).padStart(2, "0")}:30:00Z`,
    }),
  );
}

/** OV 审计透传字段尚未真机抓包固化（Q12），默认载荷仅保证可解析渲染。 */
const DEFAULT_OV_PAYLOAD: Record<string, unknown> = {
  total: 2,
  items: [
    { ts: "2026-11-01T00:00:00Z", actor: "ovadmin", action: "vm.create", target: "vm-1001" },
    { ts: "2026-11-01T01:00:00Z", actor: "ovroot", action: "acl.update", target: "group-default" },
  ],
};

let rows: AuditLog[] = defaultRows();
let listError: { status: number; body: unknown } | null = null;
let ovPayload: Record<string, unknown> = { ...DEFAULT_OV_PAYLOAD };
let ovError: { status: number; body: unknown } | null = null;

export interface CapturedRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedRequest[] = [];

export function resetAuditMock(list: AuditLog[] | null = defaultRows()): void {
  rows = list === null ? [] : list;
  listError = null;
  ovError = null;
  ovPayload = { ...DEFAULT_OV_PAYLOAD };
  captured.length = 0;
}

/** 注入 GET /audit-logs 列表错误（须在 resetAuditMock 之后调用，reset 会清空）。 */
export function setAuditError(status: number, body: unknown): void {
  listError = { status, body };
}

/** 注入 GET /audit-logs/ov 透传错误（后端 OpenVikingError 全局 handler 产物形态）。 */
export function setOvAuditError(status: number, body: unknown): void {
  ovError = { status, body };
}

export function setOvAuditPayload(payload: Record<string, unknown>): void {
  ovPayload = payload;
}

export function getAuditRequests(method?: string): CapturedRequest[] {
  return method ? captured.filter((r) => r.method === method) : [...captured];
}

export const auditHandlers: HttpHandler[] = [
  // /ov 是列表路径的更长前缀，放最前避免被列表路由先命中。
  http.get("*/api/v1/audit-logs/ov", ({ request }) => {
    captured.push({ method: "GET", url: request.url, body: null });
    if (ovError) return HttpResponse.json(ovError.body as JsonValue, { status: ovError.status });
    return HttpResponse.json(ovPayload);
  }),
  http.get("*/api/v1/audit-logs", ({ request }) => {
    captured.push({ method: "GET", url: request.url, body: null });
    if (listError) {
      return HttpResponse.json(listError.body as JsonValue, { status: listError.status });
    }
    // 回显后端 audit_service.list_logs 语义：action 前缀匹配、actor 子串匹配、page/page_size 切片。
    const search = new URL(request.url).searchParams;
    const action = search.get("action") ?? "";
    const actor = search.get("actor") ?? "";
    const page = Math.max(1, Number(search.get("page") ?? 1) || 1);
    const pageSize = Math.min(100, Math.max(1, Number(search.get("page_size") ?? 20) || 20));
    const filtered = rows.filter(
      (row) =>
        (action === "" || row.action.startsWith(action)) &&
        (actor === "" || row.actor_name.includes(actor)),
    );
    const start = (page - 1) * pageSize;
    const payload: AuditLogPage = {
      items: filtered.slice(start, start + pageSize),
      total: filtered.length,
      page,
      page_size: pageSize,
    };
    return HttpResponse.json(payload);
  }),
];
