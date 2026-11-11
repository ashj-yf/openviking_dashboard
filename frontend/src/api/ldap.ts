import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type LdapConfig = Schema["LdapConfigOut"];
export type LdapConfigUpdate = Schema["LdapConfigUpdate"];
export type LdapTestResult = Schema["LdapTestResult"];

/** LDAP 认证配置管理（管理员）；bind 密码只写不读，读取响应以 has_bind_password 标记。 */
export const ldapApi = {
  getConfig(): Promise<LdapConfig> {
    return apiRequest<LdapConfig>("GET", "/auth/ldap-config");
  },
  save(payload: LdapConfigUpdate): Promise<LdapConfig> {
    return apiRequest<LdapConfig>("PUT", "/auth/ldap-config", { body: payload });
  },
  test(payload: LdapConfigUpdate): Promise<LdapTestResult> {
    return apiRequest<LdapTestResult>("POST", "/auth/ldap-config/test", { body: payload });
  },
};
