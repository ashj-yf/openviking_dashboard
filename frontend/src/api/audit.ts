import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type AuditLog = Schema["AuditLogOut"];
export type AuditLogPage = Schema["AuditLogPageOut"];

/** 审计列表查询参数（前端局部形状；range 为 [start, end] ISO 时间区间）。 */
export interface AuditListParams {
  action?: string | null;
  actor?: string | null;
  range?: [string, string] | null;
  page: number;
  pageSize: number;
}

export const auditApi = {
  list(params: AuditListParams): Promise<AuditLogPage> {
    return apiRequest<AuditLogPage>("GET", "/audit-logs", {
      query: {
        action: params.action || undefined,
        actor: params.actor || undefined,
        start: params.range?.[0],
        end: params.range?.[1],
        page: params.page,
        page_size: params.pageSize,
      },
    });
  },
  /** OV 审计透传（唯一数据源为 OV，错误经全局 OpenVikingError handler 冒泡）。 */
  listOv(): Promise<Record<string, unknown>> {
    return apiRequest<Record<string, unknown>>("GET", "/audit-logs/ov");
  },
};
