import type { HttpHandler } from "msw";
import { authHandlers } from "./domains/auth";
import { healthHandlers } from "./domains/health";
import { tenantListHandlers } from "./domains/tenants";

export const handlers: HttpHandler[] = [
  ...authHandlers,
  ...healthHandlers,
  ...tenantListHandlers,
];
