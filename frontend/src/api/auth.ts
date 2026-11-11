import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type Me = Schema["MeOut"];
export type LoginBody = Schema["LoginRequest"];
export type Login = Schema["LoginResponse"];
export type ChangePasswordBody = Schema["ChangePasswordRequest"];

export function login(body: LoginBody): Promise<Login> {
  return apiRequest<Login>("POST", "/auth/login", { body });
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

/** LDAP 绑定：凭登录响应签发的短时 bind_token 鉴权（显式覆盖传入，绝不写入 token-store）。 */
export function ldapBind(ldapUsername: string, ldapPassword: string, bindToken: string): Promise<null> {
  return apiRequest<null>("POST", "/auth/ldap/bind", {
    body: { ldap_username: ldapUsername, ldap_password: ldapPassword },
    token: bindToken,
  });
}
