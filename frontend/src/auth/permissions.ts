export type Role = "admin" | "team_admin" | "user";

export type Permission =
  | "tenants:manage"
  | "users:manage"
  | "credentials:view";

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
  }
}
