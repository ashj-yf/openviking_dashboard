export const qk = {
  me: ["me"] as const,
  health: ["health"] as const,
  credentials: ["credentials"] as const,
  tenants: (q?: string | null) => ["tenants", q ?? ""] as const,
  tenant: (id: number) => ["tenant", id] as const,
  users: (filters: { tenant_id?: number | null; keyword?: string | null }) =>
    ["users", filters.tenant_id ?? null, filters.keyword ?? ""] as const,
  ldapConfig: ["ldapConfig"] as const,
  auditLogs: (f: {
    action?: string | null;
    actor?: string | null;
    range?: [string, string] | null;
    page: number;
    pageSize: number;
  }) =>
    [
      "auditLogs",
      f.action ?? "",
      f.actor ?? "",
      f.range ?? null,
      f.page,
      f.pageSize,
    ] as const,
  auditOv: ["auditOv"] as const,
  overviewSummary: ["overviewSummary"] as const,
  observer: ["observer"] as const,
};
