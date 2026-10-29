export const qk = {
  me: ["me"] as const,
  health: ["health"] as const,
  credentials: ["credentials"] as const,
  tenants: (q?: string | null) => ["tenants", q ?? ""] as const,
  tenant: (id: number) => ["tenant", id] as const,
  users: (filters: { tenant_id?: number | null; keyword?: string | null }) =>
    ["users", filters.tenant_id ?? null, filters.keyword ?? ""] as const,
};
