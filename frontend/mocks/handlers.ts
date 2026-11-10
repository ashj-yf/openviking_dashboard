import type { HttpHandler } from "msw";
import { authHandlers } from "./domains/auth";
import { healthHandlers } from "./domains/health";
import { tenantListHandlers } from "./domains/tenants";
import { userHandlers } from "./domains/users";

export const handlers: HttpHandler[] = [
  ...authHandlers,
  ...healthHandlers,
  ...tenantListHandlers,
  ...userHandlers,
];
