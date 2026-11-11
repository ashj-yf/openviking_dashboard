import { http, HttpResponse } from "msw";
import { server } from "@mocks/server";
import { ApiError, apiRequest, authExpired, healthRequest } from "@/api/client";
import { getToken, setToken } from "@/auth/token-store";

describe("apiRequest", () => {
  beforeEach(() => {
    localStorage.clear();
    server.resetHandlers();
  });

  it("存在 token 时附带 Authorization: Bearer 头", async () => {
    setToken("jwt-1");
    let seen = "";
    server.use(
      http.get("*/api/v1/tenants", ({ request }) => {
        seen = request.headers.get("authorization") ?? "";
        return HttpResponse.json([]);
      }),
    );
    await apiRequest("GET", "/tenants");
    expect(seen).toBe("Bearer jwt-1");
  });

  it("无 token 时不发送 Authorization 头", async () => {
    let seen: string | null = "unset";
    server.use(
      http.get("*/api/v1/tenants", ({ request }) => {
        seen = request.headers.get("authorization");
        return HttpResponse.json([]);
      }),
    );
    await apiRequest("GET", "/tenants");
    expect(seen).toBeNull();
  });

  it("200 响应解析为 JSON", async () => {
    server.use(http.get("*/api/v1/tenants", () => HttpResponse.json([{ id: 1 }])));
    const data = await apiRequest<{ id: number }[]>("GET", "/tenants");
    expect(data).toEqual([{ id: 1 }]);
  });

  it("204 响应返回 null", async () => {
    server.use(http.post("*/api/v1/users/1/disable", () => new HttpResponse(null, { status: 204 })));
    await expect(apiRequest("POST", "/users/1/disable")).resolves.toBeNull();
  });

  it("query 对象中 undefined/null/空串不进 URL，其余正确编码", async () => {
    let url = "";
    server.use(
      http.get("*/api/v1/users", ({ request }) => {
        url = request.url;
        return HttpResponse.json([]);
      }),
    );
    await apiRequest("GET", "/users", { query: { tenant_id: 7, keyword: "alice", bogus: null, empty: "" } });
    expect(url).toContain("tenant_id=7");
    expect(url).toContain("keyword=alice");
    expect(url).not.toContain("bogus");
    expect(url).not.toContain("empty=");
  });

  it("test_request_accepts_explicit_token_override", async () => {
    // 显式 token（如 LDAP bind_token）必须覆盖 token-store 中的会话 token，
    // 且覆盖值只作用于本次请求，不写入、不清除存储。
    setToken("jwt-stored");
    let seen = "";
    server.use(
      http.get("*/api/v1/tenants", ({ request }) => {
        seen = request.headers.get("authorization") ?? "";
        return HttpResponse.json([]);
      }),
    );
    await apiRequest("GET", "/tenants", { token: "jwt-explicit" });
    expect(seen).toBe("Bearer jwt-explicit");
    expect(getToken()).toBe("jwt-stored");
  });

  it("401 时清除 token、派发 authExpired 事件并抛出含 detail 的 ApiError", async () => {
    setToken("jwt-expired");
    const expired = vi.fn();
    authExpired.addEventListener("expired", expired);
    server.use(http.get("*/api/v1/auth/me", () => HttpResponse.json({ detail: "未认证" }, { status: 401 })));

    await expect(apiRequest("GET", "/auth/me")).rejects.toMatchObject({ status: 401, message: "未认证" });
    expect(getToken()).toBeNull();
    expect(expired).toHaveBeenCalledOnce();
    authExpired.removeEventListener("expired", expired);
  });

  it("test_401_on_ldap_bind_path_does_not_broadcast_expired", async () => {
    // 绑定端点的 401 意味着 bind_token 失效（走显式覆盖传入，不入 token-store），
    // 与登录端点同理：不广播过期事件，401 语义不吞、仍抛 ApiError。
    setToken("jwt-stale");
    const expired = vi.fn();
    authExpired.addEventListener("expired", expired);
    server.use(
      http.post("*/api/v1/auth/ldap/bind", () => HttpResponse.json({ detail: "未认证" }, { status: 401 })),
    );

    await expect(
      apiRequest("POST", "/auth/ldap/bind", { token: "bind-jwt", body: { ldap_username: "u", ldap_password: "p" } }),
    ).rejects.toMatchObject({ status: 401, message: "未认证" });
    expect(expired).not.toHaveBeenCalled();
    authExpired.removeEventListener("expired", expired);
  });

  it("detail 为字符串时（400/403/404/409）以其为错误文案", async () => {
    server.use(http.post("*/api/v1/users/9/disable", () => HttpResponse.json({ detail: "不能禁用自己" }, { status: 400 })));
    await expect(apiRequest("POST", "/users/9/disable")).rejects.toMatchObject({
      status: 400,
      message: "不能禁用自己",
    });
  });

  it("detail 为对象时（502 半成品）取 message 文案并保留整个 payload", async () => {
    server.use(
      http.post("*/api/v1/users", () =>
        HttpResponse.json(
          { detail: { message: "OpenViking 用户已创建但密钥签发失败，请稍后重试签发", user_id: 42 } },
          { status: 502 },
        ),
      ),
    );
    const promise = apiRequest("POST", "/users", { body: { username: "x" } });
    await expect(promise).rejects.toBeInstanceOf(ApiError);
    try {
      await promise;
    } catch (e) {
      const err = e as ApiError;
      expect(err.status).toBe(502);
      expect(err.message).toBe("OpenViking 用户已创建但密钥签发失败，请稍后重试签发");
      expect((err.detail as { detail: { user_id: number } }).detail.user_id).toBe(42);
    }
  });

  it("422 校验错误把 loc 末段映射为 fields 字典", async () => {
    server.use(
      http.post("*/api/v1/tenants", () =>
        HttpResponse.json(
          { detail: [{ loc: ["body", "account_id"], msg: "字符集不合法", type: "pattern" }] },
          { status: 422 },
        ),
      ),
    );
    await expect(apiRequest("POST", "/tenants", { body: {} })).rejects.toMatchObject({
      status: 422,
      fields: { account_id: "字符集不合法" },
    });
  });

  it("网络中断抛出统一兜底文案", async () => {
    server.use(http.get("*/api/v1/tenants", () => HttpResponse.error()));
    await expect(apiRequest("GET", "/tenants")).rejects.toMatchObject({
      status: 0,
      message: "网络异常，请稍后重试",
    });
  });
});

describe("healthRequest", () => {
  beforeEach(() => {
    localStorage.clear();
    server.resetHandlers();
  });

  it("请求 /healthz 且不带 Authorization，即使 401 也不清 token、不派 authExpired", async () => {
    setToken("jwt-keep");
    const expired = vi.fn();
    authExpired.addEventListener("expired", expired);
    server.use(
      http.get("*/healthz", ({ request }) => {
        expect(request.headers.get("authorization")).toBeNull();
        return HttpResponse.json({ detail: "nope" }, { status: 401 });
      }),
    );

    await expect(healthRequest()).rejects.toMatchObject({ status: 401 });
    expect(getToken()).toBe("jwt-keep");
    expect(expired).not.toHaveBeenCalled();
    authExpired.removeEventListener("expired", expired);
  });
});
