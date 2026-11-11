import type { HttpHandler } from "msw";
import { auditHandlers } from "./domains/audit";
import { authHandlers } from "./domains/auth";
import { credentialHandlers } from "./domains/credentials";
import { healthHandlers } from "./domains/health";
import { ldapHandlers } from "./domains/ldap";
import { tenantListHandlers } from "./domains/tenants";
import { userHandlers } from "./domains/users";

export const handlers: HttpHandler[] = [
  ...auditHandlers,
  ...authHandlers,
  ...healthHandlers,
  ...tenantListHandlers,
  ...userHandlers,
  ...credentialHandlers,
  ...ldapHandlers,
];
