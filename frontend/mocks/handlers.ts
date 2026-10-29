import type { HttpHandler } from "msw";
import { authHandlers } from "./domains/auth";

export const handlers: HttpHandler[] = [...authHandlers];
