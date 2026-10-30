import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type Me = Schema["MeOut"];
export type LoginBody = Schema["LoginRequest"];
export type Token = Schema["TokenResponse"];
export type ChangePasswordBody = Schema["ChangePasswordRequest"];

export function login(body: LoginBody): Promise<Token> {
  return apiRequest<Token>("POST", "/auth/login", { body });
}

export function logout(): Promise<null> {
  return apiRequest<null>("POST", "/auth/logout");
}

export function fetchMe(): Promise<Me> {
  return apiRequest<Me>("GET", "/auth/me");
}

export function changePassword(body: ChangePasswordBody): Promise<null> {
  return apiRequest<null>("POST", "/auth/change-password", { body });
}
