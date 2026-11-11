import { apiRequest } from "@/api/client";
import type { Schema } from "@/types/api";

export type OverviewSummary = Schema["OverviewSummaryOut"];
export type ObserverAggregate = Schema["ObserverAggregateOut"];
export type ObserverComponent = Schema["ObserverComponentOut"];

export const overviewApi = {
  summary(): Promise<OverviewSummary> {
    return apiRequest<OverviewSummary>("GET", "/overview/summary");
  },
  observer(): Promise<ObserverAggregate> {
    return apiRequest<ObserverAggregate>("GET", "/overview/observer");
  },
  observerOne(component: string): Promise<Record<string, unknown>> {
    return apiRequest<Record<string, unknown>>(
      "GET",
      `/overview/observer/${encodeURIComponent(component)}`,
    );
  },
};
