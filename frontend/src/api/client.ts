import { clearToken, getToken } from "@/auth/token-store";
import type { Paths } from "@/types/api";

/** /healthz 响应体：真实后端未声明 response_model，类型取自契约快照的内联 schema。 */
export type HealthResponse =
  Paths["/healthz"]["get"]["responses"][200]["content"]["application/json"];

const API_PREFIX = "/api/v1";
const NETWORK_MESSAGE = "网络异常，请稍后重试";
const VALIDATION_MESSAGE = "提交内容校验未通过";

export class ApiError extends Error {
  fields?: Record<string, string>;
  detail?: unknown;

  constructor(
    public readonly status: number,
    message: string,
    options?: { fields?: Record<string, string>; detail?: unknown },
  ) {
    super(message);
    this.name = "ApiError";
    this.fields = options?.fields;
    this.detail = options?.detail;
  }
}

/** 401 事件总线：client 只负责派发，路由层监听后跳转登录页（避免循环依赖）。 */
export const authExpired = new EventTarget();

export interface RequestOptions {
  body?: unknown;
  query?: Record<string, string | number | null | undefined>;
  signal?: AbortSignal;
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  const url = `${API_PREFIX}${normalized}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.append(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

function fieldErrors(detail: unknown[]): Record<string, string> {
  const fields: Record<string, string> = {};
  for (const item of detail) {
    if (typeof item !== "object" || item === null) continue;
    const loc = "loc" in item && Array.isArray(item.loc) ? item.loc : [];
    const key = loc.filter((part) => part !== "body").at(-1);
    const msg = "msg" in item ? item.msg : undefined;
    if (typeof key === "string" && typeof msg === "string") fields[key] = msg;
  }
  return fields;
}

async function parseError(response: Response): Promise<ApiError> {
  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    return new ApiError(response.status, `请求失败（${response.status}）`);
  }
  const detail = (payload as { detail?: unknown } | null)?.detail;
  if (Array.isArray(detail)) {
    return new ApiError(response.status, VALIDATION_MESSAGE, {
      fields: fieldErrors(detail),
      detail: payload,
    });
  }
  if (typeof detail === "object" && detail !== null) {
    const message =
      "message" in detail && typeof (detail as { message: unknown }).message === "string"
        ? (detail as { message: string }).message
        : `请求失败（${response.status}）`;
    return new ApiError(response.status, message, { detail: payload });
  }
  if (typeof detail === "string" && detail.length > 0) {
    return new ApiError(response.status, detail, { detail: payload });
  }
  return new ApiError(response.status, `请求失败（${response.status}）`, { detail: payload });
}

export async function apiRequest<T>(
  method: string,
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {};
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers["Authorization"] = `Bearer ${token}`;

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), {
      method,
      headers,
      body: options.body !== undefined ? JSON.stringify(options.body) : undefined,
      signal: options.signal,
    });
  } catch {
    throw new ApiError(0, NETWORK_MESSAGE);
  }

  if (!response.ok) {
    const error = await parseError(response);
    if (response.status === 401) {
      clearToken();
      // 登录端点的 401 是账密错误而非会话过期，不应广播过期事件、误导展示过期提示。
      if (!path.endsWith("/auth/login")) {
        authExpired.dispatchEvent(new Event("expired"));
      }
    }
    throw error;
  }

  if (response.status === 204) return null as T;
  return (await response.json()) as T;
}

/** 健康探针：与业务 API 隔离，不带 token、401 不触发登出事件。 */
export async function healthRequest(signal?: AbortSignal): Promise<HealthResponse> {
  let response: Response;
  try {
    response = await fetch("/healthz", { signal });
  } catch {
    throw new ApiError(0, NETWORK_MESSAGE);
  }
  if (!response.ok) throw new ApiError(response.status, `健康检查失败（${response.status}）`);
  return (await response.json()) as HealthResponse;
}
