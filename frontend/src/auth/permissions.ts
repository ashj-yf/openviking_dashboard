export type Role = "admin" | "team_admin" | "user";

export type Permission =
  | "tenants:manage"
  | "users:manage"
  | "credentials:view"
  | "ldap:manage"
  | "audit:view"
  | "overview:view";

export function homePathFor(role: string | undefined): string {
  if (role === "admin") return "/tenants";
  if (role === "team_admin") return "/users";
  return "/credentials";
}

export function can(role: string | undefined, permission: Permission): boolean {
  switch (permission) {
    case "tenants:manage":
      return role === "admin";
    case "users:manage":
      return role === "admin" || role === "team_admin";
    case "credentials:view":
      return role === "team_admin" || role === "user";
    case "ldap:manage":
      return role === "admin";
    case "audit:view":
      // 审计日志：admin 全量只读；team_admin 本团队只读。
      return role === "admin" || role === "team_admin";
    case "overview:view":
      // 总览看板：admin 全量；team_admin 收窄版（本团队视角）。
      return role === "admin" || role === "team_admin";
  }
}
