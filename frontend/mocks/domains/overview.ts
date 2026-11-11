import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type OverviewSummary = Schema["OverviewSummaryOut"];
type ObserverAggregate = Schema["ObserverAggregateOut"];
type ObserverComponent = Schema["ObserverComponentOut"];

/** setOverviewError / setObserverError 注入的是测试夹具 JSON；交予 MSW 响应前以此精确收窄（不用 any，同 audit.ts）。 */
type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

/** observer 七组件 key（与后端 OBSERVER_COMPONENTS 顺序一致）。 */
export const OBSERVER_KEYS = [
  "queue",
  "models",
  "retrieval",
  "system",
  "vikingdb",
  "filesystem",
  "lock",
] as const;

export type ObserverKey = (typeof OBSERVER_KEYS)[number];

export function makeSummary(overrides: Partial<OverviewSummary> = {}): OverviewSummary {
  return {
    tenant_count: 3,
    users_total: 12,
    users_active: 10,
    users_disabled: 2,
    ov_summary: { users: 12, tenants: 3, viking_collections: 5 },
    ov_health: { status: "ok", version: "v1.2.0", latency_ms: 42 },
    ov_error: null,
    ...overrides,
  };
}

export function makeComponent(
  key: ObserverKey,
  overrides: Partial<ObserverComponent> = {},
): ObserverComponent {
  return { data: { component: key, ok: true }, error: null, ...overrides };
}

/** 七组件聚合工厂：默认全绿，components 传入的键覆盖默认形态（单组件异常场景）。 */
export function makeObserver(
  components: Partial<Record<ObserverKey, ObserverComponent>> = {},
): ObserverAggregate {
  const defaults = Object.fromEntries(
    OBSERVER_KEYS.map((key) => [key, makeComponent(key)]),
  ) as Record<ObserverKey, ObserverComponent>;
  return { components: { ...defaults, ...components } };
}

let summary: OverviewSummary = makeSummary();
let observer: ObserverAggregate = makeObserver();
let summaryError: { status: number; body: unknown } | null = null;
let observerError: { status: number; body: unknown } | null = null;

export interface CapturedRequest {
  method: string;
  url: string;
  body: unknown;
}
const captured: CapturedRequest[] = [];

export function resetOverviewMock(
  next: { summary?: OverviewSummary; observer?: ObserverAggregate } = {},
): void {
  summary = next.summary ?? makeSummary();
  observer = next.observer ?? makeObserver();
  summaryError = null;
  observerError = null;
  captured.length = 0;
}

/** 注入 GET /overview/summary 端点级错误（须在 resetOverviewMock 之后调用，reset 会清空）。 */
export function setOverviewError(status: number, body: unknown): void {
  summaryError = { status, body };
}

/** 注入 GET /overview/observer 聚合端点错误。 */
export function setObserverError(status: number, body: unknown): void {
  observerError = { status, body };
}

export function getOverviewRequests(method?: string): CapturedRequest[] {
  return method ? captured.filter((r) => r.method === method) : [...captured];
}

export const overviewHandlers: HttpHandler[] = [
  // /observer/:component 是更长路径，放最前避免被聚合路由先命中（同 audit.ts 的 /ov 先例）。
  http.get("*/api/v1/overview/observer/:component", ({ request, params }) => {
    captured.push({ method: "GET", url: request.url, body: null });
    const entry = observer.components[String(params.component)];
    if (!entry) {
      return HttpResponse.json({ detail: "未知 observer 组件" }, { status: 404 });
    }
    return HttpResponse.json(entry);
  }),
  http.get("*/api/v1/overview/observer", ({ request }) => {
    captured.push({ method: "GET", url: request.url, body: null });
    if (observerError) {
      return HttpResponse.json(observerError.body as JsonValue, {
        status: observerError.status,
      });
    }
    return HttpResponse.json(observer);
  }),
  http.get("*/api/v1/overview/summary", ({ request }) => {
    captured.push({ method: "GET", url: request.url, body: null });
    if (summaryError) {
      return HttpResponse.json(summaryError.body as JsonValue, {
        status: summaryError.status,
      });
    }
    // team_admin 场景无需特判：夹具形状由测试经 resetOverviewMock({ summary: makeSummary({...}) })
    // 决定（tenant_count 置 null、ov_summary 置 undefined），权限收窄是后端职责。
    return HttpResponse.json(summary);
  }),
];
