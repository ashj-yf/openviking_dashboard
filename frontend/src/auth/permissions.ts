export type Role = "admin" | "team_admin" | "user";

export function homePathFor(role: string | undefined): string {
  if (role === "admin") return "/tenants";
  if (role === "team_admin") return "/users";
  return "/credentials";
}
