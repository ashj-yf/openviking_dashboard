import { http, HttpResponse, type HttpHandler } from "msw";
import type { Schema } from "@/types/api";

type Health = Schema["HealthResponse"];

const DEFAULT_HEALTH: Health = {
  status: "ok",
  db: true,
  openviking: true,
  version: "v0.4.14",
};

let body: Health = DEFAULT_HEALTH;
let networkError = false;

export function resetHealthMock(
  overrides: Partial<Health> & { networkError?: boolean } = {},
): void {
  const { networkError: fail = false, ...fields } = overrides;
  body = { ...DEFAULT_HEALTH, ...fields };
  networkError = fail;
}

export const healthHandlers: HttpHandler[] = [
  http.get("*/healthz", () =>
    networkError ? HttpResponse.error() : HttpResponse.json(body),
  ),
];
