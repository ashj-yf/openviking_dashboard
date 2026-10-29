import type { HttpHandler } from "msw";
import { authHandlers } from "./domains/auth";
import { healthHandlers } from "./domains/health";

export const handlers: HttpHandler[] = [...authHandlers, ...healthHandlers];
