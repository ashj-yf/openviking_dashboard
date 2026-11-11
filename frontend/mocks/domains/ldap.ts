import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type LdapConfigOut = Schema["LdapConfigOut"];
type LdapTestResult = Schema["LdapTestResult"];

/** setLdapConfigError/setLdapTestError 注入的是测试夹具 JSON；在交予 MSW 响应前以此精确收窄（不用 any）。 */
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** 与后端 GET /auth/ldap-config 空行默认值逐字对齐（api/v1/auth.py _config_out 的 None 分支）。 */
export function makeLdapConfig(overrides: Partial<LdapConfigOut> = {}): LdapConfigOut {
  return {
    enabled: false,
    server_host: "",
    server_port: 389,
    encryption: "none",
    bind_dn: null,
    user_base_dn: "",
    user_filter: "(uid={username})",
    attr_uid: "uid",
    attr_mail: "mail",
    attr_display_name: "cn",
    has_bind_password: false,
    updated_at: null,
    ...overrides,
  };
}

export function makeTestResult(overrides: Partial<LdapTestResult> = {}): LdapTestResult {
  return { ok: true, stage: "ok", message: "连接、绑定与用户搜索均正常", ...overrides };
}

let config: LdapConfigOut = makeLdapConfig();
let configError: { status: number; body: JsonValue } | null = null;
let testResult: LdapTestResult = makeTestResult();
let testError: { status: number; body: JsonValue } | null = null;

export interface CapturedLdapRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedLdapRequest[] = [];

/** 每个测试 beforeEach 调用；传 makeLdapConfig(...) 预置已保存配置，null 回到默认空白配置。 */
export function resetLdapMock(next: LdapConfigOut | null = makeLdapConfig()): void {
  config = next ?? makeLdapConfig();
  configError = null;
  testResult = makeTestResult();
  testError = null;
  captured.length = 0;
}

/** 注入 GET/PUT /auth/ldap-config 错误（须在 resetLdapMock 之后调用，reset 会清空）。 */
export function setLdapConfigError(status: number, body: unknown): void {
  configError = { status, body: body as JsonValue };
}

/** 覆盖 POST /auth/ldap-config/test 的返回体（成功/失败两态均走同一 handler）。 */
export function setLdapTestResult(result: LdapTestResult): void {
  testResult = result;
}

export function setLdapTestError(status: number, body: unknown): void {
  testError = { status, body: body as JsonValue };
}

export function getLdapRequests(method?: string): CapturedLdapRequest[] {
  return method ? captured.filter((r) => r.method === method) : [...captured];
}

/** PUT 落库语义对齐后端 upsert：bind_password 缺省/None 保留旧密文（has_bind_password 不翻转）。 */
function applyUpdate(body: Schema["LdapConfigUpdate"]): void {
  config = {
    ...config,
    enabled: body.enabled,
    server_host: body.server_host,
    server_port: body.server_port,
    encryption: body.encryption,
    bind_dn: body.bind_dn ?? null,
    user_base_dn: body.user_base_dn,
    user_filter: body.user_filter,
    attr_uid: body.attr_uid,
    attr_mail: body.attr_mail,
    attr_display_name: body.attr_display_name,
    has_bind_password: body.bind_password ? true : config.has_bind_password,
    updated_at: new Date().toISOString(),
  };
}

export const ldapHandlers: HttpHandler[] = [
  http.get("*/api/v1/auth/ldap-config", () => {
    if (configError) {
      return HttpResponse.json(configError.body, { status: configError.status });
    }
    return HttpResponse.json(config);
  }),
  http.put("*/api/v1/auth/ldap-config", async ({ request }) => {
    const body = (await request.json()) as Schema["LdapConfigUpdate"];
    captured.push({ method: "PUT", url: request.url, body });
    if (configError) {
      return HttpResponse.json(configError.body, { status: configError.status });
    }
    applyUpdate(body);
    return HttpResponse.json(config);
  }),
  http.post("*/api/v1/auth/ldap-config/test", async ({ request }) => {
    const body = (await request.json()) as Schema["LdapConfigUpdate"];
    captured.push({ method: "POST", url: request.url, body });
    if (testError) {
      return HttpResponse.json(testError.body, { status: testError.status });
    }
    return HttpResponse.json(testResult);
  }),
];
