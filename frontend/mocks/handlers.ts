import type { HttpHandler } from "msw";
import { auditHandlers } from "./domains/audit";
import { authHandlers } from "./domains/auth";
import { credentialHandlers } from "./domains/credentials";
import { healthHandlers } from "./domains/health";
import { ldapHandlers } from "./domains/ldap";
import { overviewHandlers } from "./domains/overview";
import { tenantListHandlers } from "./domains/tenants";
import { userHandlers } from "./domains/users";

export const handlers: HttpHandler[] = [
  ...auditHandlers,
  ...authHandlers,
  ...healthHandlers,
  ...overviewHandlers,
  ...tenantListHandlers,
  ...userHandlers,
  ...credentialHandlers,
  ...ldapHandlers,
];
