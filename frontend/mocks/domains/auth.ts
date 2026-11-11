import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type Me = Schema["MeOut"];
type Token = Schema["TokenResponse"];

const ROLE_BY_USERNAME: Record<string, Me["role"]> = {
  admin: "admin",
  boss: "team_admin",
  alice: "user",
};

export function makeMe(overrides: Partial<Me> = {}): Me {
  return {
    id: 1,
    username: "admin",
    role: "admin",
    is_active: true,
    tenant_id: null,
    account_id: null,
    ov_user_id: null,
    ov_role: null,
    has_ov_key: false,
    key_synced_at: null,
    must_change_password: false,
    last_login_at: null,
    is_env_admin: false,
    ...overrides,
  };
}

let me: Me | null = null;

export interface CapturedAuthRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedAuthRequest[] = [];

export function getAuthRequests(method?: string): CapturedAuthRequest[] {
  return method ? captured.filter((r) => r.method === method) : [...captured];
}

/** 每个测试 beforeEach 调用；传入 makeMe(...) 模拟已登录会话，null 模拟未登录。 */
export function resetAuthMock(next: Me | null = null): void {
  me = next;
  captured.length = 0;
}

function tokenFor(username: string): Token {
  const role = ROLE_BY_USERNAME[username] ?? "user";
  return { access_token: `jwt-${username}`, token_type: "bearer", expires_in: 43200, role };
}

export const authHandlers: HttpHandler[] = [
  http.post("*/api/v1/auth/login", async ({ request }) => {
    const body = (await request.json()) as { username: string; password: string };
    if (body.password === "wrong") {
      return HttpResponse.json({ detail: "用户名或密码错误" }, { status: 401 });
    }
    me = makeMe({
      id: me?.id ?? (body.username === "admin" ? 1 : 10),
      username: body.username,
      role: ROLE_BY_USERNAME[body.username] ?? "user",
      tenant_id: body.username === "admin" ? null : 1,
      account_id: body.username === "admin" ? null : "acme",
      ov_user_id: body.username === "admin" ? null : body.username,
      ov_role: body.username === "boss" ? "admin" : body.username === "admin" ? null : "user",
      has_ov_key: body.username !== "admin",
    });
    return HttpResponse.json(tokenFor(body.username));
  }),
  http.post("*/api/v1/auth/logout", ({ request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    me = null;
    return new HttpResponse(null, { status: 204 });
  }),
  http.get("*/api/v1/auth/me", () =>
    me ? HttpResponse.json(me) : HttpResponse.json({ detail: "未认证" }, { status: 401 }),
  ),
  http.post("*/api/v1/auth/change-password", async ({ request }) => {
    const body = (await request.json()) as { old_password: string; new_password: string };
    if (body.old_password === "bad-old") {
      return HttpResponse.json({ detail: "旧密码不正确" }, { status: 400 });
    }
    if (me) me = { ...me, must_change_password: false };
    return new HttpResponse(null, { status: 204 });
  }),
];
