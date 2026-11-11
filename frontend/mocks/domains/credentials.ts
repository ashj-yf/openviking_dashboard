import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type CredentialView = Schema["CredentialView"];
type RevealedKey = Schema["RevealedKeyOut"];

/** setCredentialError 注入的是测试夹具 JSON；在交予 MSW 响应前以此精确收窄（不用 any）。 */
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** 白盒固定明文：只允许出现在 reveal/copy/regenerate 三个响应里，泄漏扫描据此断言。 */
export const PLAIN_CREDENTIAL_KEY = "ovk-abcd-SECRET-1234567890-wxyz";
export const ROTATED_CREDENTIAL_KEY = "ovk-eeee-ROTATED-99998888-aaaa";

export function makeCredential(overrides: Partial<CredentialView> = {}): CredentialView {
  return {
    endpoint: "https://ov.example.com",
    account_id: "acme",
    ov_user_id: "alice",
    has_key: true,
    key_masked: "ovk-a************wxyz",
    key_hint: "ovk-abcd",
    seed_used: false,
    key_synced_at: "2026-10-29T08:00:00Z",
    ...overrides,
  };
}

let view: CredentialView = makeCredential();
let actionError: { method: string; status: number; body: unknown } | null = null;

export interface CapturedCredentialRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedCredentialRequest[] = [];

export function resetCredentialsMock(next: CredentialView | null = null): void {
  view = next ?? makeCredential();
  actionError = null;
  captured.length = 0;
}

export function setCredentialError(method: string, status: number, body: unknown): void {
  actionError = { method, status, body };
}

export function getCredentialRequests(method?: string): CapturedCredentialRequest[] {
  return method ? captured.filter((r) => r.method === method) : [...captured];
}

function revealed(key: string): RevealedKey {
  return { ...view, key };
}

export const credentialHandlers: HttpHandler[] = [
  http.get("*/api/v1/credentials", () => HttpResponse.json(view)),
  http.post("*/api/v1/credentials/reveal", ({ request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    if (actionError?.method === "reveal") {
      return HttpResponse.json(actionError.body as JsonValue, { status: actionError.status });
    }
    return HttpResponse.json(revealed(PLAIN_CREDENTIAL_KEY));
  }),
  http.post("*/api/v1/credentials/copy", ({ request }) => {
    captured.push({ method: "POST", url: request.url, body: null });
    if (actionError?.method === "copy") {
      return HttpResponse.json(actionError.body as JsonValue, { status: actionError.status });
    }
    return HttpResponse.json(revealed(PLAIN_CREDENTIAL_KEY));
  }),
  http.post("*/api/v1/credentials/regenerate", async ({ request }) => {
    const body = (await request.json()) as Record<string, unknown>;
    captured.push({ method: "POST", url: request.url, body });
    if (actionError?.method === "regenerate") {
      return HttpResponse.json(actionError.body as JsonValue, { status: actionError.status });
    }
    view = {
      ...view,
      key_masked: "ovk-e************aaaa",
      key_hint: "ovk-eeee",
      key_synced_at: "2026-10-29T10:00:00Z",
    };
    return HttpResponse.json(revealed(ROTATED_CREDENTIAL_KEY));
  }),
];
